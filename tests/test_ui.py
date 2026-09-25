import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox
from zuoban.ui import Window
from zuoban.core import Engine, Config, KEYS


def test_window_starts_without_camera(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window(tmp_path / "models", tmp_path / "data")
    assert window.pipeline is None
    assert window.tabs.count() == 3
    assert not window.calibrate_button.isEnabled()
    window.show()
    app.processEvents()
    window.close()


def test_session_pause_finish_report_and_raw_export(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window(tmp_path / "models", tmp_path / "data")
    window.engine = Engine(dict(pitch=0, roll=0, shoulder=0, yaw=0), Config())
    window.session = window.store.start(window.engine.metadata())
    sid = window.session
    window.pause()
    assert window.paused
    assert set(window.store.rows(sid)[-1]["states"].values()) == {"paused"}
    window.pause()
    assert not window.paused
    window.finish_session()
    window.history.selectRow(0)
    window.show_report()
    assert "有效监测" in window.report.text()
    assert window.store.sessions()[0][2] == "finished"
    window.close()


def test_calibrate_finishes_old_session(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = Window(tmp_path / "models", tmp_path / "data")
    window.engine = Engine(dict(pitch=0, roll=0, shoulder=0, yaw=0), Config())
    window.session = window.store.start(window.engine.metadata())
    window.calibrate()
    assert window.engine is None
    assert window.calibrator is not None
    assert window.session is None
    assert window.store.sessions()[0][2] == "finished"
    assert not window.pause_button.isEnabled()
    window.close()


def test_threshold_settings_validate_and_persist(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = Window(tmp_path / "models", tmp_path / "data")
    notices = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: notices.append("saved"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: notices.append("invalid"))
    window.enter_inputs["pitch"].setValue(7.5)
    window.exit_inputs["pitch"].setValue(8.0)
    window.save_settings()
    assert notices == ["invalid"]
    assert window.config.enter["pitch"] == 10.0
    assert window.store.settings() == {}
    window.exit_inputs["pitch"].setValue(4.0)
    window.hold_input.setValue(3)
    window.save_settings()
    assert notices[-1] == "saved"
    assert window.store.settings()["enter"]["pitch"] == 7.5
    assert window.store.settings()["hold"] == 3
    window.close()
