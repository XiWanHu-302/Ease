from pathlib import Path
import subprocess
import sys
import json
from zuoban.core import Config, Engine, Measurement
from zuoban.storage import Store


def test_replay_preserves_database_and_emits_variants(tmp_path):
    db = tmp_path / "replay.sqlite3"
    store = Store(db)
    engine = Engine(dict(pitch=8, roll=0, shoulder=0, yaw=0), Config())
    sid = store.start(engine.metadata())
    for i in range(151):
        m = Measurement(i / 10, dict(pitch=20, roll=0, shoulder=0), yaw=0)
        row = dict(engine.update(m), t=m.timestamp, values=m.values, yaw=m.yaw)
        store.append(sid, row)
    store.db.commit()
    result = subprocess.run([sys.executable, "tools/replay.py", "--database", str(db), "--session", str(sid),
                             "--output-dir", str(tmp_path / "out")], cwd=Path(__file__).resolve().parents[1],
                             capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert store.sessions()[0][2] == "running"
    summaries = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert summaries["A_fixed"]["alerts"]["pitch"] > 10
    assert summaries["B_calibrated"]["alerts"]["pitch"] == 0
    assert summaries["C_temporal"]["alerts"]["pitch"] == 0
    store.close()
