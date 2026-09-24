"""生成开发版运行包与源码包，不包含个人会话、测试截图或虚拟环境。"""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]


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
    sources = [ROOT / name for name in ("main.py", "README.md", "CONTRIBUTING.md", "THIRD_PARTY_NOTICES.md", "pyproject.toml",
                                       "requirements.in", "requirements-dev.in", "requirements-lock.txt", "start.ps1", ".gitignore")]
    for folder in ("zuoban", "tools", "tests", "docs", "models", "licenses", "packaging"):
        sources.extend((ROOT / folder).rglob("*"))
    summaries.append(archive(out / "ZuoBan-0.1.0-source.zip", sources, ROOT))
    (out / "checksums.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
