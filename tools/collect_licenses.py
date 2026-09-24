"""收集实际安装分发包的许可证文本，便于随目录包分发。"""
from importlib import metadata
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / "licenses"
    target.mkdir(exist_ok=True)
    entries = []
    for dist in metadata.distributions():
        name = dist.metadata["Name"]
        entry = {"name": name, "version": dist.version,
                 "license": dist.metadata.get("License-Expression") or dist.metadata.get("License"),
                 "source": dist.metadata.get_all("Project-URL", []), "files": []}
        for file in dist.files or []:
            if any(part.lower().startswith(("license", "licence", "copying", "notice")) for part in file.parts):
                original = Path(dist.locate_file(file))
                if original.is_file() and original.stat().st_size < 3_000_000:
                    output = target / name / Path(*file.parts)
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(original.read_bytes())
                    entry["files"].append(str(output.relative_to(target)))
        entries.append(entry)
    (target / "packages.json").write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Collected notices for {len(entries)} installed distributions")


if __name__ == "__main__":
    main()
