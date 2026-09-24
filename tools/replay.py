"""重放会话原始数值。输出实验对照事件，不自动构造人工标签或准确率。"""
import argparse
import csv
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zuoban.core import Config, Engine, Measurement, KEYS, summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--session", required=True, type=int)
    parser.add_argument("--output-dir", type=Path, default=Path("output/replay"))
    args = parser.parse_args()
    # 只读连接，不能通过Store初始化把正在运行的会话标记中断。
    db = sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)
    entry = db.execute("SELECT metadata FROM sessions WHERE id=?", (args.session,)).fetchone()
    if entry is None:
        parser.error("Session not found")
    metadata = json.loads(entry[0])
    samples = [json.loads(r[0]) for r in db.execute("SELECT payload FROM samples WHERE session_id=? ORDER BY t", (args.session,))]
    db.close()
    if not samples or not any("values" in s for s in samples):
        parser.error("Session has no raw measurements")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    comparison = {}
    origin = samples[0]["t"]
    for variant in ("A_fixed", "B_calibrated", "C_temporal"):
        config = Config(**metadata["config"])
        baseline = dict.fromkeys((*KEYS, "yaw"), 0.0) if variant == "A_fixed" else metadata["baseline"]
        engine = Engine(baseline, config)
        if variant != "C_temporal":
            # 仅实验对照允许0秒等待；生产设置仍要求至少2秒。
            engine.config.hold = 0.0
            engine.config.recovery = 0.0
        outputs = []
        for sample in samples:
            m = Measurement(sample["t"], sample.get("values", dict.fromkeys(KEYS)),
                            sample.get("reasons", {}), sample.get("yaw"), sample.get("ratio"))
            result = engine.update(m, paused="paused" in sample["states"].values())
            outputs.append(dict(result, t=m.timestamp))
        with (args.output_dir / f"{variant}.csv").open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["elapsed_s", *KEYS, "notices"])
            for row in outputs:
                writer.writerow([row["t"] - origin, *(row["states"][k] for k in KEYS), ";".join(row["notices"])])
        comparison[variant] = summarize(outputs)
    comparison["note"] = "仅输出算法对照结果。检出率、误提醒必须与独立人工标签对齐后计算；这些汇总不是准确率。"
    (args.output_dir / "summary.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved replay outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
