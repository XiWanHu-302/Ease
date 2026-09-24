"""下载固定版本模型。仅此脚本需要网络；正式软件不会联网。"""
from pathlib import Path
import hashlib
import json
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "face_landmarker.task": "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
    "pose_landmarker_lite.task": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
}


def main():
    folder = ROOT / "models"
    folder.mkdir(exist_ok=True)
    manifest = {}
    for name, url in MODELS.items():
        path = folder / name
        if not path.exists():
            print(f"Downloading {name}", flush=True)
            temp = path.with_suffix(".download")
            with urllib.request.urlopen(url, timeout=120) as response:
                temp.write_bytes(response.read())
            if not zipfile.is_zipfile(temp):
                raise RuntimeError(f"Invalid task bundle: {name}")
            temp.replace(path)
        manifest[name] = {"url": url, "bytes": path.stat().st_size,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
