"""直接检查打包exe；不打开摄像头，不依赖系统Python来运行软件本体。"""
from pathlib import Path
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    exe = ROOT / "dist" / "ZuoBan" / "ZuoBan.exe"
    out = ROOT / "output"
    out.mkdir(exist_ok=True)
    results = {}
    cases = {
        "model": (["--self-check", "--output", str(out / "packaged-model-check.json")], out / "packaged-model-check.json"),
        "ui": (["--ui-smoke", "--data-dir", str(out / "packaged-qa-data"), "--output", str(out / "packaged-ui.png")], out / "packaged-ui.png"),
    }
    for name, (args, artifact) in cases.items():
        before = artifact.stat().st_mtime_ns if artifact.exists() else 0
        try:
            run = subprocess.run([str(exe), *args], cwd=ROOT, capture_output=True, timeout=45)
            fresh = artifact.exists() and artifact.stat().st_mtime_ns > before
            results[name] = {"exit_code": run.returncode, "fresh_output": fresh, "passed": run.returncode == 0 and fresh}
        except subprocess.TimeoutExpired:
            results[name] = {"passed": False, "error": "timeout"}
    (out / "release-check.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    return 0 if all(r["passed"] for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
