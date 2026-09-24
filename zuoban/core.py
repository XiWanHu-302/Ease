"""纯 Python 姿态状态机；不依赖摄像头、Qt 或模型，可重放和测试。"""
from dataclasses import dataclass, field, asdict
import math
import statistics

KEYS = ("pitch", "roll", "shoulder")
LABELS = {"pitch": "低头", "roll": "歪头", "shoulder": "肩部倾斜"}
STATES = {"normal": "参考范围内", "pending": "偏离待确认", "alert": "持续偏离",
          "unknown": "无法判断", "paused": "已暂停"}
VERSION = "angles-v1"


def angle_delta(value, baseline):
    return (value - baseline + 180.0) % 360.0 - 180.0


@dataclass
class Config:
    camera: int = 0
    hold: float = 10.0
    recovery: float = 3.0
    cooldown: float = 60.0
    smoothing: float = 0.5
    stale: float = 0.5
    sound: bool = True
    volume: int = 40
    enter: dict = field(default_factory=lambda: dict(pitch=15.0, roll=12.0, shoulder=8.0))
    exit: dict = field(default_factory=lambda: dict(pitch=10.0, roll=8.0, shoulder=5.0))

    def validate(self):
        if not 0 <= self.camera <= 20 or not 0 <= self.volume <= 100:
            raise ValueError("摄像头编号或音量超出范围")
        if not all(math.isfinite(x) and x > 0 for x in
                   (self.hold, self.recovery, self.cooldown, self.smoothing, self.stale)):
            raise ValueError("时间参数必须是有限正数")
        if not 2 <= self.hold <= 60 or self.cooldown < 60:
            raise ValueError("提醒等待应为2至60秒，提醒间隔至少60秒")
        for key in KEYS:
            if not 0 < self.exit[key] < self.enter[key] < 90:
                raise ValueError("恢复阈值必须小于偏离阈值，且都在0至90度之间")
        return self


@dataclass
class Measurement:
    timestamp: float
    values: dict
    reasons: dict = field(default_factory=dict)
    yaw: float | None = None
    ratio: float | None = None


class Calibrator:
    """要求连续10秒有效稳定数据；无效或间隔过大即重新积累。"""
    def __init__(self, duration=10.0):
        self.duration = duration
        self.samples = []
        self.message = "请面向屏幕，自然坐直，保持脸和双肩完整可见"

    def feed(self, m):
        valid = all(m.values.get(k) is not None and math.isfinite(m.values[k]) for k in KEYS)
        valid = valid and m.yaw is not None and abs(m.yaw) <= 25
        if not valid or (self.samples and m.timestamp - self.samples[-1].timestamp > 0.5):
            self.samples.clear()
            self.message = "取景无效或中断，请保持正面、脸和双肩完整可见"
        if not valid:
            return None
        self.samples.append(m)
        span = self.samples[-1].timestamp - self.samples[0].timestamp
        self.message = f"保持自然坐直，校准中 {min(span, self.duration):.1f}/{self.duration:.0f} 秒"
        if span < self.duration:
            return None
        if len(self.samples) < self.duration * 5:
            self.samples.clear()
            self.message = "有效采样不足，请检查性能后重试"
            return None
        baseline = {k: statistics.median(s.values[k] for s in self.samples) for k in KEYS}
        spread = {k: statistics.pstdev(angle_delta(s.values[k], baseline[k]) for s in self.samples) for k in KEYS}
        if any(spread[k] > (2.0 if k == "shoulder" else 3.0) for k in KEYS):
            self.samples.clear()
            self.message = "校准时动作变化过大，已重新计时"
            return None
        baseline["yaw"] = statistics.median(s.yaw for s in self.samples)
        self.message = "校准完成；移动机位或屏幕角度后请重新校准"
        return baseline


class Axis:
    def __init__(self):
        self.state = "unknown"
        self.filtered = None
        self.last_time = None
        self.since = None
        self.recover_since = None
        self.last_notice = -math.inf

    def invalidate(self, state="unknown"):
        self.state = state
        self.filtered = self.last_time = self.since = self.recover_since = None

    def update(self, key, value, t, config):
        if self.last_time is not None and t - self.last_time > config.stale:
            self.invalidate()
        dt = 0 if self.last_time is None else max(0, t - self.last_time)
        alpha = 1 - math.exp(-dt / config.smoothing)
        self.filtered = value if self.filtered is None else self.filtered + alpha * angle_delta(value, self.filtered)
        self.last_time = t
        severity = self.filtered if key == "pitch" else abs(self.filtered)
        if self.state == "alert":
            if severity <= config.exit[key]:
                if self.recover_since is None:
                    self.recover_since = t
                if t - self.recover_since >= config.recovery:
                    self.state, self.since, self.recover_since = "normal", None, None
            else:
                self.recover_since = None
        elif severity >= config.enter[key]:
            if self.since is None:
                self.since = t
            self.state = "alert" if t - self.since >= config.hold else "pending"
        else:
            self.state, self.since = "normal", None
        notice = self.state == "alert" and t - self.last_notice >= config.cooldown
        if notice:
            self.last_notice = t
        return notice


class Engine:
    def __init__(self, baseline, config):
        self.baseline = dict(baseline)
        self.config = config.validate()
        self.axes = {k: Axis() for k in KEYS}
        self.last_timestamp = None

    def update(self, m, now=None, paused=False):
        now = m.timestamp if now is None else now
        if self.last_timestamp is not None and m.timestamp < self.last_timestamp:
            raise ValueError("检测时间戳不能倒退")
        self.last_timestamp = m.timestamp
        notices, reasons = [], dict(m.reasons)
        for key, axis in self.axes.items():
            value = m.values.get(key)
            reason = None
            if paused:
                reason = "监测已暂停"
            elif now - m.timestamp > self.config.stale:
                reason = "检测结果已过期"
            elif value is None or not math.isfinite(value):
                reason = reasons.get(key, "关键点不可用")
            elif key in ("pitch", "roll") and (m.yaw is None or not math.isfinite(m.yaw) or abs(angle_delta(m.yaw, self.baseline["yaw"])) > 30):
                reason = "侧转角度过大，请面向屏幕"
            if reason:
                axis.invalidate("paused" if paused else "unknown")
                reasons[key] = reason
                continue
            delta = angle_delta(value, self.baseline[key])
            if axis.update(key, delta, m.timestamp, self.config):
                notices.append(key)
        return {"states": {k: a.state for k, a in self.axes.items()},
                "deltas": {k: a.filtered for k, a in self.axes.items()},
                "reasons": reasons, "notices": notices}

    def metadata(self):
        return {"algorithm": VERSION, "baseline": self.baseline, "config": asdict(self.config)}


def summarize(rows):
    """积分相邻时刻；样本最多有效0.5秒，总偏离取三项并集。"""
    valid = dict.fromkeys(KEYS, 0.0)
    alerts = dict.fromkeys(KEYS, 0.0)
    union = active = 0.0
    notices = dict.fromkeys(KEYS, 0)
    for i, row in enumerate(rows):
        for k in row.get("notices", []):
            notices[k] += 1
        if i + 1 == len(rows):
            continue
        dt = min(0.5, max(0.0, rows[i + 1]["t"] - row["t"]))
        states = row["states"]
        for k in KEYS:
            if states[k] in ("normal", "pending", "alert"):
                valid[k] += dt
            if states[k] == "alert":
                alerts[k] += dt
        if any(s in ("normal", "pending", "alert") for s in states.values()):
            active += dt
        if "alert" in states.values():
            union += dt
    return {"valid": valid, "alerts": alerts, "union": union, "active": active, "notices": notices}
