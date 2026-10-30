"""生成运行包与已跟踪源码包；不纳入本地模型和个人数据。"""
from pathlib import Path
import hashlib
import json
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def source_files(root):
    """从Git索引取公开文件，避免递归收集未跟踪的本地资料。"""
    result = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    paths = []
    for name in result.stdout.decode("utf-8").split("\0"):
        if not name:
            continue
        relative = Path(name)
        if relative.parts[0] == "x" or relative.name == "AGENTS.md" or relative.suffix == ".task":
            continue
        path = root / relative
        if path.is_file() and not path.is_symlink():
            paths.append(path)
    return paths


def archive(target, paths, relative_to):
    count = 0
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(paths):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix not in (".pyc", ".download"):
                z.write(path, path.relative_to(relative_to).as_posix())
                count += 1
    return {"file": target.name, "files": count, "bytes": target.stat().st_size,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}


def main():
    out = ROOT / "output" / "release"
    out.mkdir(parents=True, exist_ok=True)
    runtime = ROOT / "dist" / "ZuoBan"
    if not (runtime / "ZuoBan.exe").exists():
        raise RuntimeError("Build executable first")
    summaries = [archive(out / "ZuoBan-0.1.0-Windows-x64.zip", runtime.rglob("*"), runtime.parent)]
    summaries.append(archive(out / "ZuoBan-0.1.0-source.zip", source_files(ROOT), ROOT))
    (out / "checksums.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
