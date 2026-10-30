"""按仓库清单下载并校验固定版本模型；正式软件不会联网。"""
from pathlib import Path
import hashlib
import json
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def verify_model(path, expected):
    """已有模型和新下载模型都必须匹配版本清单。"""
    size = path.stat().st_size
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if size != expected["bytes"] or digest != expected["sha256"] or not zipfile.is_zipfile(path):
        raise RuntimeError(f"模型校验失败：{path.name}。请删除损坏文件后重新下载。")


def main():
    folder = ROOT / "models"
    folder.mkdir(exist_ok=True)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest.items():
        if Path(name).name != name or not name.endswith(".task"):
            raise ValueError(f"模型清单包含无效文件名：{name}")
        path = folder / name
        if not path.exists():
            print(f"Downloading {name}", flush=True)
            temp = path.with_suffix(".download")
            try:
                with urllib.request.urlopen(expected["url"], timeout=120) as response:
                    temp.write_bytes(response.read())
                verify_model(temp, expected)
            except Exception:
                temp.unlink(missing_ok=True)
                raise
            temp.replace(path)
        else:
            verify_model(path, expected)
        print(f"Verified {name}: {expected['sha256']}")


if __name__ == "__main__":
    main()
