import math
import pytest
from zuoban.core import Config, Measurement, Engine, Calibrator, KEYS, summarize
from zuoban.storage import Store


def measurement(t, pitch=0, roll=0, shoulder=0, yaw=0):
    return Measurement(t, dict(pitch=pitch, roll=roll, shoulder=shoulder), yaw=yaw)


def engine():
    return Engine(dict(pitch=0, roll=0, shoulder=0, yaw=0), Config())


def advance(e, start, end, **values):
    results = []
    for i in range(round(start * 10), round(end * 10) + 1):
        results.append(e.update(measurement(i / 10, **values)))
    return results


def test_short_motion_does_not_alert():
    e = engine()
    rows = advance(e, 0, 4, pitch=25)
    rows += advance(e, 4.1, 8)
    assert not any(r["notices"] for r in rows)
    assert rows[-1]["states"]["pitch"] == "normal"


def test_three_independent_alerts_and_cooldown():
    rows = advance(engine(), 0, 80, pitch=25, roll=20, shoulder=15)
    notices = [(i / 10, r["notices"]) for i, r in enumerate(rows) if r["notices"]]
    assert notices == [(10.0, list(KEYS)), (70.0, list(KEYS))]


def test_head_up_not_head_down():
    rows = advance(engine(), 0, 20, pitch=-30)
    assert rows[-1]["states"]["pitch"] == "normal"


def test_invalid_resets_continuous_hold_and_is_independent():
    e = engine()
    advance(e, 0, 9, pitch=25, shoulder=15)
    r = e.update(measurement(9.1, pitch=None, shoulder=15))
    assert r["states"]["pitch"] == "unknown"
    rows = advance(e, 9.2, 11, pitch=25, shoulder=15)
    assert rows[-1]["states"]["pitch"] == "pending"
    assert rows[-1]["states"]["shoulder"] == "alert"


def test_nan_yaw_and_large_yaw_are_not_valid():
    e = engine()
    r = e.update(measurement(0, yaw=40))
    assert r["states"]["pitch"] == "unknown"
    assert r["states"]["shoulder"] == "normal"
    r = e.update(measurement(0.1, yaw=math.nan))
    assert r["states"]["pitch"] == "unknown"


def test_stale_and_gap_reset_hold():
    e = engine()
    advance(e, 0, 9, pitch=25)
    r = e.update(measurement(10, pitch=25), now=11)
    assert r["states"]["pitch"] == "unknown"
    assert e.update(measurement(11.1, pitch=25))["states"]["pitch"] == "pending"
    assert e.update(measurement(30, pitch=25))["states"]["pitch"] == "pending"


def test_pause_resets_but_keeps_cooldown():
    e = engine()
    advance(e, 0, 11, pitch=25)
    r = e.update(measurement(11.1, pitch=25), paused=True)
    assert set(r["states"].values()) == {"paused"}
    rows = advance(e, 11.2, 23, pitch=25)
    assert rows[-1]["states"]["pitch"] == "alert"
    assert not any(r["notices"] for r in rows)


def test_recovery_requires_continuous_three_seconds():
    e = engine()
    advance(e, 0, 11, pitch=25)
    advance(e, 11.1, 13, pitch=0)
    assert e.axes["pitch"].state == "alert"
    advance(e, 13.1, 18, pitch=0)
    assert e.axes["pitch"].state == "normal"


def test_timestamp_cannot_go_backwards():
    e = engine()
    e.update(measurement(1))
    with pytest.raises(ValueError):
        e.update(measurement(0.9))


def test_calibration_stable_and_invalid_reset():
    c = Calibrator()
    for i in range(90):
        assert c.feed(measurement(i / 10)) is None
    assert c.feed(measurement(9, shoulder=None)) is None
    baseline = None
    for i in range(91, 193):
        baseline = c.feed(measurement(i / 10, pitch=2, shoulder=1))
        if baseline:
            break
    assert baseline == dict(pitch=2, roll=0, shoulder=1, yaw=0)


def test_calibration_rejects_unstable_sequence():
    c = Calibrator()
    for i in range(101):
        result = c.feed(measurement(i / 10, pitch=20 if i % 2 else -20))
    assert result is None
    assert "变化过大" in c.message


def test_union_and_missing_time_not_double_counted():
    rows = [dict(t=0, states=dict.fromkeys(KEYS, "alert"), notices=list(KEYS)),
            dict(t=0.1, states=dict.fromkeys(KEYS, "unknown")),
            dict(t=5, states=dict.fromkeys(KEYS, "normal")),
            dict(t=6, states=dict.fromkeys(KEYS, "paused"))]
    summary = summarize(rows)
    assert summary["union"] == pytest.approx(0.1)
    assert summary["active"] == pytest.approx(0.6)
    assert summary["alerts"]["pitch"] == pytest.approx(0.1)
    assert summary["notices"]["pitch"] == 1


def test_storage_roundtrip_interrupted_and_export(tmp_path):
    path = tmp_path / "test.sqlite3"
    store = Store(path)
    sid = store.start(engine().metadata())
    store.append(sid, dict(t=1, states=dict.fromkeys(KEYS, "normal")))
    store.close()
    store = Store(path)
    assert store.sessions()[0][2] == "interrupted"
    target = tmp_path / "report.csv"
    store.export(sid, target)
    assert "elapsed_s" in target.read_text(encoding="utf-8-sig")
    assert len(store.rows(sid)) == 1
    store.clear()
    assert store.sessions() == []
    store.close()


def test_bad_config_rejected():
    with pytest.raises(ValueError):
        Config(hold=-1).validate()
    with pytest.raises(ValueError):
        Config(enter=dict(pitch=1, roll=12, shoulder=8)).validate()
