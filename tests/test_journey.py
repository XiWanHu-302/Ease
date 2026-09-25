"""日历与旅程共享的真实存储路径。"""
from datetime import date, datetime, time, timedelta, timezone

import pytest

from zuoban.core import KEYS
from zuoban.journey import GOALS, station_for
from zuoban.storage import Store


def row(t, state="normal", notices=()):
    return {"t": t, "states": dict.fromkeys(KEYS, state), "notices": list(notices)}


def test_daily_split_at_local_midnight_and_reopen(tmp_path):
    path = tmp_path / "days.sqlite3"
    store = Store(path)
    sid = store.start({"journey_enabled": True})
    yesterday = date.today() - timedelta(days=1)
    local_start = datetime.combine(yesterday, time(23, 59, 59, 800000)).astimezone()
    started_utc = local_start.astimezone(timezone.utc).isoformat()
    store.db.execute("UPDATE sessions SET started=? WHERE id=?", (started_utc, sid))
    store.append(sid, row(0))
    store.append(sid, row(0.4, notices=("pitch",)))
    store.finish(sid)
    before = store.day_summary(yesterday.isoformat())
    after = store.day_summary(date.today().isoformat())
    assert before["active"] == pytest.approx(0.2, abs=0.02)
    assert after["active"] == pytest.approx(0.2, abs=0.02)
    assert after["notices"]["pitch"] == 1
    assert before["sessions"] == after["sessions"] == 1
    store.close()
    store = Store(path)
    assert store.day_summary(date.today().isoformat()) == after
    store.clear()
    assert store.month_days(date.today().year, date.today().month) == {}
    assert store.journey_history() == []
    store.close()


def test_legacy_backfill_shows_calendar_but_no_retroactive_reward(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    store = Store(path)
    sid = store.start({})
    store.append(sid, row(0))
    store.append(sid, row(0.2))
    store.close()  # 模拟升级前中断、无完成标记的会话
    store = Store(path)
    today = date.today().isoformat()
    assert store.day_summary(today)["active"] == pytest.approx(0.2)
    assert store.sessions()[0][2] == "interrupted"
    assert store.journey_progress(today)["total_completed"] == 0
    store.close()


def test_seven_stage_rules_and_no_reward_from_unknown_or_disabled(tmp_path):
    assert GOALS == (15, 20, 25, 20, 25, 20, 15)
    assert station_for(0) == (1, 1, 15)
    assert station_for(6) == (1, 7, 15)
    assert station_for(7) == (2, 1, 15)
    store = Store(tmp_path / "rewards.sqlite3")
    sid = store.start({"journey_enabled": True})
    for i in range(1802):
        state = "unknown" if i < 2 else "alert"
        unlocked = store.append(sid, row(i * 0.5, state))
    assert unlocked == []  # 前 1 秒无效，尚未到 15 分钟
    assert store.append(sid, row(901)) == [date.today().isoformat()]
    assert store.append(sid, row(901.5)) == []
    progress = store.journey_progress(date.today().isoformat())
    assert progress["completed_today"] == (1, 1)
    assert progress["station"] == 2
    assert store.day_summary(date.today().isoformat())["alerts"]["pitch"] > 0
    store.finish(sid)
    store.close()
    store = Store(tmp_path / "rewards.sqlite3")
    assert store.journey_progress(date.today().isoformat())["total_completed"] == 1
    store.set_journey_enabled(False)
    sid2 = store.start({"journey_enabled": False})
    store.append(sid2, row(0))
    store.append(sid2, row(0.5))
    store.finish(sid2)
    assert len(store.journey_history()) == 1
    store.close()
