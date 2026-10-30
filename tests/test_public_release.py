"""检查公开源码清单和下载模型校验，不生成发布包。"""
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

import pytest

from tools.download_models import verify_model
from tools.package_release import ROOT, source_files


def test_source_manifest_excludes_local_files():
    paths = {path.relative_to(ROOT).as_posix() for path in source_files(ROOT)}
    assert {"README.md", "zuoban/core.py", "models/manifest.json"} <= paths
    assert all(not path.startswith("x/") for path in paths)
    assert all(not path.endswith(".task") for path in paths)
    assert "AGENTS.md" not in paths


def test_model_verification_rejects_changed_bytes(tmp_path):
    path = Path(tmp_path) / "model.task"
    with ZipFile(path, "w") as bundle:
        bundle.writestr("model", b"example")
    data = path.read_bytes()
    expected = {"bytes": len(data), "sha256": sha256(data).hexdigest()}
    verify_model(path, expected)
    changed = bytearray(data)
    changed[-1] ^= 1
    path.write_bytes(changed)
    with pytest.raises(RuntimeError, match="模型校验失败"):
        verify_model(path, expected)
