"""本地视频/图片或空画面CPU基准；不把空画面指标当作真人使用指标。"""
import argparse
import json
import os
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cv2
import numpy as np
import psutil
from zuoban.vision import Detector


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, help="获得同意的本地测试视频或图片；省略则只测试空画面")
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--output", type=Path, default=Path("output/benchmark.json"))
    args = parser.parse_args()
    if args.frames < 1:
        parser.error("frames must be positive")
    detector = Detector(Path(__file__).resolve().parents[1] / "models")
    cap = None
    static = None
    if args.input:
        if not args.input.is_file():
            parser.error("Input file does not exist")
        static = cv2.imdecode(np.fromfile(args.input, dtype=np.uint8), cv2.IMREAD_COLOR)
        if static is None:
            cap = cv2.VideoCapture(str(args.input))
            if not cap.isOpened():
                parser.error("Cannot open input video")
    else:
        static = np.zeros((480, 640, 3), dtype=np.uint8)
    process = psutil.Process()
    cpu0 = process.cpu_times()
    start = time.perf_counter()
    times, valid = [], {k: 0 for k in ("pitch", "roll", "shoulder")}
    peak = 0
    try:
        for i in range(args.frames):
            frame = static
            if cap:
                ok, frame = cap.read()
                if not ok:
                    break
            frame = cv2.resize(frame, (640, 480))
            before = time.perf_counter()
            m, _ = detector.detect(frame, i * 0.1 + 1)
            times.append((time.perf_counter() - before) * 1000)
            for k in valid:
                valid[k] += int(m.values[k] is not None)
            peak = max(peak, process.memory_info().rss)
    finally:
        detector.close()
        if cap:
            cap.release()
    elapsed = time.perf_counter() - start
    cpu1 = process.cpu_times()
    cpu_percent = ((cpu1.user + cpu1.system) - (cpu0.user + cpu0.system)) / max(elapsed, 0.001) * 100
    result = {
        "source": str(args.input) if args.input else "blank frame (no human)",
        "scope": "单进程CPU离线推理基准，不含相机/UI延迟，不是动作准确率或真实场景有效覆盖率",
        "platform": platform.platform(), "cpu": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
        "logical_processors": psutil.cpu_count(), "frames": len(times),
        "inference_fps": len(times) / max(sum(times) / 1000, 0.001),
        "latency_ms_p50": float(np.percentile(times, 50)) if times else None,
        "latency_ms_p95": float(np.percentile(times, 95)) if times else None,
        "peak_rss_mb": peak / 1024 ** 2,
        "cpu_percent_one_core_100": cpu_percent,
        "cpu_percent_total_machine": cpu_percent / (psutil.cpu_count() or 1),
        "frames_with_raw_measurement": valid,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
