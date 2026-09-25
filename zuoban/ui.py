"""桌面界面。摄像头只在用户点击开启后访问，后台线程不操作Qt控件。"""
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import math
import time

import cv2
from PySide6.QtCore import Qt, QTimer, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PySide6.QtMultimedia import QAudioFormat, QAudioSink
from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QFrame, QGridLayout, QFormLayout, QSpinBox, QDoubleSpinBox, QCheckBox,
    QSlider, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox,
    QProgressBar, QScrollArea)

from .core import KEYS, LABELS, STATES, Config, Measurement, Calibrator, Engine, load_config
from .storage import Store
from .vision import Pipeline
from .journey import GOALS, STATIONS
from .ui_journey import JourneyMap, UsageCalendar

COLORS = {"normal": "#17655D", "pending": "#AD7137", "alert": "#C35E51", "unknown": "#74857F", "paused": "#74857F"}


class Tone:
    def __init__(self, parent):
        import struct
        fmt = QAudioFormat()
        fmt.setSampleRate(24000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        samples = [int(7500 * math.sin(2 * math.pi * 660 * n / 24000) * (1 - n / 4800)) for n in range(4800)]
        self.data = QByteArray(struct.pack("<" + "h" * len(samples), *samples))
        self.buffer = QBuffer(parent)
        self.buffer.setData(self.data)
        self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self.audio = QAudioSink(fmt, parent)

    def play(self, volume):
        self.audio.stop()
        self.buffer.seek(0)
        self.audio.setVolume(volume / 100)
        self.audio.start(self.buffer)


class Timeline(QWidget):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.setMinimumHeight(135)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#FFFDF8"))
        if not self.rows:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "选择一次会话查看状态时间线")
            return
        start, end = self.rows[0]["t"], self.rows[-1]["t"]
        duration = max(1, end - start)
        width = max(1, self.width() - 120)
        for j, key in enumerate(KEYS):
            y = 14 + j * 34
            painter.setPen(QColor("#31524B"))
            painter.drawText(8, y + 17, LABELS[key])
            painter.fillRect(100, y, width, 22, QColor("#E8EAE1"))
            for row, nxt in zip(self.rows, self.rows[1:]):
                x = 100 + (row["t"] - start) / duration * width
                span = min(0.5, max(0, nxt["t"] - row["t"])) / duration * width
                painter.fillRect(int(x), y, max(1, int(span)), 22, QColor(COLORS[row["states"][key]]))


class Window(QMainWindow):
    def __init__(self, model_dir, data_dir):
        super().__init__()
        self.model_dir, self.data_dir = Path(model_dir), Path(data_dir)
        self.store = Store(self.data_dir / "zuoban.sqlite3")
        warning = None
        try:
            self.config, migrated = load_config(self.store.settings())
            if migrated:
                self.store.save_settings(asdict(self.config))
        except (TypeError, ValueError, KeyError):
            self.config = Config()
            warning = "配置无效，已恢复默认设置。"
        self.pipeline = self.engine = self.calibrator = self.session = None
        self.seen = 0
        self.paused = False
        self.last_result = self.last_row = None
        self.last_flush = time.monotonic()
        self.last_expire = 0.0
        self.last_journey_refresh = 0.0
        self.tone = None
        self.setWindowTitle("坐伴 · 个性化姿态提醒")
        self.resize(1180, 840)
        self.setMinimumSize(900, 680)
        self.setStyleSheet("""
            QMainWindow, QWidget { background:#FAF7F0; color:#29443D; font-family:'Microsoft YaHei'; font-size:14px; }
            QTabWidget::pane { border:0; }
            QTabBar::tab { padding:12px 28px; background:#EEEDE4; margin-right:6px; border-radius:8px; }
            QTabBar::tab:selected { background:#175C55; color:white; }
            QPushButton { background:#17655D; color:white; border:0; border-radius:9px; padding:10px 18px; }
            QPushButton:disabled { background:#D4DAD2; color:#6D7B75; }
            QPushButton:hover { background:#258076; }
            QSpinBox, QDoubleSpinBox { background:#FFFDF8; padding:7px; border:1px solid #D8DAD1; border-radius:6px; }
            QTableWidget, QCalendarWidget { background:#FFFDF8; gridline-color:#E8EAE1; }
            QCalendarWidget QAbstractItemView { selection-background-color:#17655D; selection-color:white; }
            QProgressBar { background:#E8EAE1; border:0; border-radius:7px; height:14px; text-align:center; }
            QProgressBar::chunk { background:#D78968; border-radius:7px; }
            QFrame#card { background:#FFFDF8; border:1px solid #E2E4DA; border-radius:12px; }
            QFrame#card QLabel { background:transparent; }
        """)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(26, 18, 26, 18)
        title = QLabel("坐伴  /  让专注更自在")
        title.setFont(QFont("Microsoft YaHei", 23, QFont.Weight.Bold))
        title.setStyleSheet("font-size:26px; font-weight:700; color:#174C45; margin-bottom:4px;")
        layout.addWidget(title)
        layout.addWidget(QLabel("本地处理 · CPU可用 · 默认不保存画面"))
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.make_monitor()
        self.make_reports()
        self.make_settings()
        self.tabs.currentChanged.connect(self.on_tab_changed)
        self.setCentralWidget(root)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(50)
        self.refresh_reports()
        if warning:
            self.status.setText(warning)

    def make_monitor(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        self.status = QLabel("先开启摄像头，再校准5秒。请保证脸和双肩完整入镜。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        body = QHBoxLayout()
        self.preview = QLabel("摄像头尚未开启\n\n画面只在你的电脑内处理")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(560, 340)
        self.preview.setStyleSheet("background:#173F3D; color:#F5EFE3; border-radius:12px; font-size:17px;")
        body.addWidget(self.preview, 3)
        cards = QVBoxLayout()
        self.cards = {}
        for key in KEYS:
            card = QFrame()
            card.setObjectName("card")
            inner = QVBoxLayout(card)
            heading = QLabel(LABELS[key])
            heading.setFont(QFont("Microsoft YaHei", 16, QFont.Weight.Bold))
            heading.setStyleSheet("font-size:19px; font-weight:600;")
            state, detail = QLabel("等待校准"), QLabel("相对参考角度 —")
            detail.setWordWrap(True)
            inner.addWidget(heading)
            inner.addWidget(state)
            inner.addWidget(detail)
            cards.addWidget(card)
            self.cards[key] = state, detail
        body.addLayout(cards, 2)
        layout.addLayout(body, 1)
        self.metrics = QLabel("CPU模式  |  低头采用人脸朝向估计；头肩距离仅作实验记录")
        self.metrics.setWordWrap(True)
        layout.addWidget(self.metrics)
        self.journey_banner = QLabel("")
        self.journey_banner.setStyleSheet("background:#F9E7D8; color:#77513B; padding:8px; border-radius:8px;")
        self.journey_banner.hide()
        layout.addWidget(self.journey_banner)
        controls = QHBoxLayout()
        self.start_button = QPushButton("开启摄像头")
        self.calibrate_button = QPushButton("校准并开始监测")
        self.pause_button = QPushButton("暂停")
        self.stop_button = QPushButton("结束会话")
        for button, callback in ((self.start_button, self.start_camera), (self.calibrate_button, self.calibrate),
                                 (self.pause_button, self.pause), (self.stop_button, self.stop)):
            controls.addWidget(button)
            button.clicked.connect(callback)
        layout.addLayout(controls)
        note = QLabel("仅提示相对参考姿态的持续变化，不诊断疾病。移动屏幕或摄像头后，请重新校准。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs.addTab(page, "实时监测")
        self.controls(False)

    def controls(self, running):
        self.start_button.setEnabled(not running)
        self.calibrate_button.setEnabled(running)
        self.pause_button.setEnabled(running and self.engine is not None)
        self.stop_button.setEnabled(running)

    def make_reports(self):
        page, outer = QWidget(), QVBoxLayout()
        page.setLayout(outer)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content, layout = QWidget(), QVBoxLayout()
        content.setLayout(layout)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        top = QHBoxLayout()
        left = QVBoxLayout()
        title = QLabel("七站陪伴旅程")
        title.setStyleSheet("font-size:20px; font-weight:700; color:#174C45;")
        left.addWidget(title)
        self.journey_map = JourneyMap()
        left.addWidget(self.journey_map)
        self.quest = QLabel("")
        self.quest.setWordWrap(True)
        left.addWidget(self.quest)
        self.quest_progress = QProgressBar()
        left.addWidget(self.quest_progress)
        left.addWidget(QLabel("完成一站后可以休息；姿态提醒不会扣除旅程进度。"))
        self.journey_history = QLabel("")
        self.journey_history.setWordWrap(True)
        left.addWidget(self.journey_history)
        top.addLayout(left, 3)
        right = QVBoxLayout()
        right.addWidget(QLabel("使用日历  ·  圆点表示使用，菱形表示完成关卡"))
        self.calendar = UsageCalendar()
        self.calendar.currentPageChanged.connect(self.refresh_month)
        self.calendar.selectionChanged.connect(self.show_day)
        right.addWidget(self.calendar)
        top.addLayout(right, 2)
        layout.addLayout(top)
        self.day_heading = QLabel("")
        self.day_heading.setStyleSheet("font-size:18px; font-weight:600; color:#174C45;")
        layout.addWidget(self.day_heading)
        self.day_details = QLabel("")
        self.day_details.setWordWrap(True)
        layout.addWidget(self.day_details)
        self.history = QTableWidget(0, 3)
        self.history.setHorizontalHeaderLabels(["会话", "开始时间（本地）", "完成状态"])
        self.history.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.history.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history.itemSelectionChanged.connect(self.show_report)
        self.history.setMinimumHeight(115)
        self.history.setMaximumHeight(145)
        layout.addWidget(self.history)
        self.report = QLabel("尚无会话。完成校准后会自动开始记录。")
        self.report.setWordWrap(True)
        layout.addWidget(self.report)
        self.timeline = Timeline()
        self.timeline.setMaximumHeight(135)
        layout.addWidget(self.timeline)
        layout.addWidget(QLabel("时间线：绿色 正常 / 黄色 待确认 / 红色 持续偏离 / 灰色 无效或暂停"))
        buttons = QHBoxLayout()
        for text, callback in (("刷新记录", self.refresh_reports), ("导出CSV", self.export)):
            b = QPushButton(text)
            b.clicked.connect(callback)
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self.tabs.addTab(page, "旅程与日历")
        self.refresh_month()
        self.refresh_journey()
        self.show_day()

    def make_settings(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.camera_input = QSpinBox()
        self.camera_input.setRange(0, 20)
        self.camera_input.setValue(self.config.camera)
        self.hold_input = QSpinBox()
        self.hold_input.setRange(2, 60)
        self.hold_input.setSuffix(" 秒")
        self.hold_input.setValue(int(self.config.hold))
        self.sound_input = QCheckBox("开启轻声提醒")
        self.sound_input.setChecked(self.config.sound)
        self.volume_input = QSlider(Qt.Orientation.Horizontal)
        self.volume_input.setRange(0, 100)
        self.volume_input.setValue(self.config.volume)
        form.addRow("摄像头编号", self.camera_input)
        form.addRow("持续偏离后提醒", self.hold_input)
        self.enter_inputs, self.exit_inputs = {}, {}
        for key in KEYS:
            row = QHBoxLayout()
            enter = QDoubleSpinBox()
            enter.setRange(0.1, 89.9)
            enter.setDecimals(1)
            enter.setSingleStep(0.5)
            enter.setSuffix("°")
            enter.setValue(self.config.enter[key])
            leave = QDoubleSpinBox()
            leave.setRange(0.1, 89.9)
            leave.setDecimals(1)
            leave.setSingleStep(0.5)
            leave.setSuffix("°")
            leave.setValue(self.config.exit[key])
            row.addWidget(QLabel("偏离 ≥"))
            row.addWidget(enter)
            row.addWidget(QLabel("恢复 ≤"))
            row.addWidget(leave)
            form.addRow(LABELS[key], row)
            self.enter_inputs[key], self.exit_inputs[key] = enter, leave
        form.addRow("声音", self.sound_input)
        form.addRow("音量", self.volume_input)
        self.journey_input = QCheckBox("显示旅程与关卡奖励")
        self.journey_input.setChecked(self.store.journey_enabled())
        form.addRow("趣味功能", self.journey_input)
        layout.addLayout(form)
        save = QPushButton("保存设置（结束当前会话后生效）")
        save.clicked.connect(self.save_settings)
        layout.addWidget(save)
        info = QLabel(f"数据位置：{self.data_dir}\n默认随当前Windows用户自动变化；启动时可用 --data-dir 指定其他目录。\n\n偏离角度按个人校准值计算；恢复角度须小于偏离角度，以减少状态反复跳变。\n默认偏离阈值：低头10° / 歪头8° / 肩线6°。这是待真人验证的工程参数。\n\n每次启动或调整机位后重新校准；不自动适应长期偏离姿态。")
        info.setWordWrap(True)
        layout.addWidget(info)
        clear = QPushButton("清除全部会话记录")
        clear.clicked.connect(self.clear_data)
        layout.addWidget(clear)
        layout.addStretch()
        self.tabs.addTab(page, "设置")

    def start_camera(self):
        if self.pipeline is not None:
            return
        self.pipeline = Pipeline(self.config.camera, self.model_dir)
        self.seen = 0
        self.last_result = None
        self.journey_banner.hide()
        self.pipeline.start()
        self.controls(True)
        self.calibrate_button.setEnabled(False)
        self.status.setText("正在加载本地模型与摄像头…")

    def calibrate(self):
        self.finish_session()
        self.engine = None
        self.calibrator = Calibrator()
        self.paused = False
        self.pause_button.setText("暂停")
        self.pause_button.setEnabled(False)
        self.status.setText(self.calibrator.message)
        for state, detail in self.cards.values():
            state.setText("等待校准")
            state.setStyleSheet("color:#758397; font-size:19px;")
            detail.setText("保持脸和双肩完整入镜")

    def pause(self):
        self.paused = not self.paused
        self.pause_button.setText("继续监测" if self.paused else "暂停")
        self.status.setText("已暂停计时，摄像头预览仍开启" if self.paused else "监测已继续")
        self.synthetic_state("paused" if self.paused else "unknown")

    def synthetic_state(self, state):
        if self.engine is None:
            return
        now = time.monotonic()
        m = Measurement(now, dict.fromkeys(KEYS), {k: "等待有效画面" for k in KEYS})
        result = self.engine.update(m, paused=state == "paused")
        self.render_states(result)
        self.record(now, result)

    def finish_session(self, status="finished"):
        if self.session is not None:
            self.synthetic_state("paused")
            self.store.finish(self.session, status)
            self.session = None
            self.refresh_reports()

    def stop(self, error=None):
        self.finish_session("interrupted" if error else "finished")
        self.engine = self.calibrator = None
        if self.pipeline:
            self.pipeline.stop()
        self.controls(False)
        self.start_button.setEnabled(False)
        self.status.setText(error or "会话已结束，报告已保存。正在释放摄像头…")
        self.preview.clear()
        self.preview.setText("摄像头已停止")

    def tick(self):
        if self.pipeline is None:
            return
        if self.pipeline.stop_event.is_set():
            if self.engine or self.calibrator or self.stop_button.isEnabled():
                self.stop(self.pipeline.error or None)
            if not self.pipeline.alive():
                self.pipeline = None
                self.start_button.setEnabled(True)
            return
        serial, packet = self.pipeline.results.get()
        now = time.monotonic()
        if packet is None or serial == self.seen:
            if self.last_result is not None and now - self.last_result > 0.5 and now - self.last_expire >= 0.5:
                self.last_expire = now
                self.synthetic_state("paused" if self.paused else "unknown")
                if self.calibrator:
                    self.calibrator.feed(Measurement(now, dict.fromkeys(KEYS)))
                    self.status.setText(self.calibrator.message)
                self.preview.setText("画面中断，正在等待摄像头")
            return
        self.seen = serial
        m = packet.measurement
        # UI控制动作后排队的旧结果不得让状态机时间倒退。
        if self.engine and self.engine.last_timestamp is not None and m.timestamp < self.engine.last_timestamp:
            return
        previous = self.last_result
        self.last_result = m.timestamp
        fps = 0 if previous is None else 1 / max(0.001, m.timestamp - previous)
        if now - m.timestamp > 0.5:
            if self.calibrator:
                self.calibrator.feed(Measurement(now, dict.fromkeys(KEYS)))
            self.synthetic_state("paused" if self.paused else "unknown")
            self.status.setText("结果延迟过大，暂不判断姿态")
            return
        rgb = cv2.cvtColor(cv2.flip(packet.frame, 1), cv2.COLOR_BGR2RGB)
        image = QImage(rgb.data, rgb.shape[1], rgb.shape[0], rgb.strides[0], QImage.Format.Format_RGB888).copy()
        self.preview.setPixmap(QPixmap.fromImage(image).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self.calibrate_button.setEnabled(True)
        ratio = "—" if m.ratio is None else f"{m.ratio:.3f}"
        raw = " / ".join("—" if m.values[k] is None else f"{m.values[k]:.1f}°" for k in KEYS)
        self.metrics.setText(f"CPU · {fps:.1f} 组/秒 · 更新延迟 {(now-m.timestamp)*1000:.0f} ms\n原始角度（俯仰/歪头/肩线）：{raw}  |  头肩距离比：{ratio}（实验指标）")
        if self.calibrator:
            baseline = self.calibrator.feed(m)
            self.status.setText(self.calibrator.message)
            if baseline:
                self.engine = Engine(baseline, self.config)
                self.session = self.store.start({**self.engine.metadata(),
                                                 "journey_enabled": self.store.journey_enabled()})
                self.calibrator = None
                self.pause_button.setEnabled(True)
                self.calibrate_button.setText("重新校准")
        if self.engine:
            result = self.engine.update(m, now, self.paused)
            self.render_states(result)
            self.record(m.timestamp, result, m, (now - m.timestamp) * 1000)
            current_alerts = [LABELS[k] for k in KEYS if result["states"][k] == "alert"]
            if self.paused:
                self.status.setText("已暂停计时，摄像头预览仍开启")
            elif current_alerts:
                self.status.setText("持续偏离，请调整：" + "、".join(current_alerts))
            elif "unknown" in result["states"].values():
                self.status.setText("部分项目暂时无法判断，请查看右侧提示并调整取景。")
            else:
                self.status.setText("监测中；短暂动作不会立即提醒，移动机位后请重新校准。")
            if result["notices"]:
                self.status.setText("请调整姿态：" + "、".join(LABELS[k] for k in result["notices"]))
                if self.config.sound:
                    try:
                        if self.tone is None:
                            self.tone = Tone(self)
                        self.tone.play(self.config.volume)
                    except Exception:
                        self.status.setText(self.status.text() + "（音频不可用，保留文字提醒）")
        elif not self.calibrator:
            self.status.setText("画面已就绪，请自然坐直并点击校准。")
        if now - self.last_flush > 1:
            self.store.db.commit()
            self.last_flush = now
        if self.tabs.currentIndex() == 1 and now - self.last_journey_refresh > 1:
            self.refresh_journey()
            self.refresh_month()
            self.last_journey_refresh = now

    def render_states(self, result):
        for k, (state, detail) in self.cards.items():
            value = result["deltas"][k]
            state.setText(STATES[result["states"][k]])
            state.setStyleSheet(f"color:{COLORS[result['states'][k]]}; font-size:19px; font-weight:600;")
            detail.setText(result["reasons"].get(k, "相对参考：" + ("—" if value is None else f"{value:+.1f}°")))

    def record(self, t, result, m=None, latency=None):
        if self.session is None:
            return
        row = dict(result, t=t, values=dict(m.values) if m else dict.fromkeys(KEYS),
                   yaw=m.yaw if m else None, ratio=m.ratio if m else None, latency_ms=latency)
        unlocked = self.store.append(self.session, row)
        self.last_row = row
        if unlocked:
            self.journey_banner.setText("今日关卡完成！做得好，记得起身休息。到「旅程与日历」看看新站点。")
            self.journey_banner.show()
            self.refresh_reports()

    def refresh_reports(self):
        self.refresh_month()
        self.refresh_journey()
        self.show_day()

    def on_tab_changed(self, index):
        if index == 1:
            self.refresh_reports()

    def refresh_month(self, *args):
        self.calendar.days = self.store.month_days(self.calendar.yearShown(), self.calendar.monthShown())
        self.calendar.updateCells()

    def refresh_journey(self):
        from datetime import date
        progress = self.store.journey_progress(date.today().isoformat())
        enabled = self.store.journey_enabled()
        count = progress["total_completed"]
        finished_seventh_today = bool(progress["completed_today"] and progress["completed_today"][1] == len(GOALS))
        self.journey_map.completed = len(GOALS) if finished_seventh_today else count % len(GOALS)
        self.journey_map.current = 0 if finished_seventh_today else progress["station"]
        self.journey_map.enabled = enabled
        self.journey_map.update()
        name, story = STATIONS[progress["station"] - 1]
        if enabled:
            if progress["completed_today"]:
                finished_journey, finished_station = progress["completed_today"]
                message = (f"今天已完成第 {finished_journey} 程 · 第 {finished_station} 站。"
                           f"下一站「{name}」已解锁：{story} 明天再继续，先休息一下。")
            else:
                message = (f"第 {progress['journey']} 程 · 第 {progress['station']} 站「{name}」\n"
                           f"{story} 今日有效监测 {progress['today_active']/60:.1f} / {progress['goal']} 分钟")
        else:
            message = "旅程已关闭。使用日历与会话报告仍可查看。"
        self.quest.setText(message)
        if progress["completed_today"]:
            self.quest_progress.setMaximum(100)
            self.quest_progress.setValue(100)
        else:
            self.quest_progress.setMaximum(progress["goal"] * 60)
            self.quest_progress.setValue(min(progress["goal"] * 60, int(progress["today_active"])))
        history = self.store.journey_history()
        full_journeys = count // len(GOALS)
        items = "  ·  ".join(f"{day} 第{journey}程第{station}站" for day, journey, station in history[:3])
        self.journey_history.setText(f"已走完 {full_journeys} 程 · 最近足迹：{items or '尚未解锁关卡'}")

    def show_day(self):
        day = self.calendar.selectedDate().toString("yyyy-MM-dd")
        data = self.store.day_summary(day)
        self.day_heading.setText(f"{day} · 当天记录")
        self.day_details.setText(
            f"有效监测 {data['active']/60:.1f} 分钟  ·  会话 {data['sessions']} 次  ·  持续偏离并集 {data['union']/60:.1f} 分钟\n"
            + "  |  ".join(f"{LABELS[k]}：持续偏离 {data['alerts'][k]/60:.1f} 分钟、提醒 {data['notices'][k]} 次" for k in KEYS))
        sessions = self.store.day_sessions(day)
        self.history.blockSignals(True)
        self.history.setRowCount(len(sessions))
        for row, (sid, started, status) in enumerate(sessions):
            values = [str(sid), datetime.fromisoformat(started).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                      {"running": "监测中", "finished": "已结束", "interrupted": "异常中断"}[status]]
            for col, value in enumerate(values):
                self.history.setItem(row, col, QTableWidgetItem(value))
        self.history.blockSignals(False)
        if sessions:
            self.history.selectRow(0)
        else:
            self.report.setText("当天没有会话记录。")
            self.timeline.rows = []
            self.timeline.update()

    def selected_session(self):
        row = self.history.currentRow()
        item = self.history.item(row, 0) if row >= 0 else None
        return int(item.text()) if item else None

    def show_report(self):
        session = self.selected_session()
        if session is None:
            return
        result = self.store.summary(session)
        lines = [f"有效监测（任一项）：{result['active']/60:.1f} 分钟   |   持续偏离并集：{result['union']:.1f} 秒"]
        for k in KEYS:
            lines.append(f"{LABELS[k]}：有效 {result['valid'][k]:.1f} 秒 / 持续偏离 {result['alerts'][k]:.1f} 秒 / 提醒 {result['notices'][k]} 次")
        self.report.setText("\n".join(lines))
        self.timeline.rows = self.store.rows(session)
        self.timeline.update()

    def export(self):
        session = self.selected_session()
        if session is None:
            QMessageBox.information(self, "导出", "请先选择一次会话。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出会话", f"坐伴-会话{session}.csv", "CSV (*.csv)")
        if path:
            try:
                self.store.export(session, path)
                QMessageBox.information(self, "导出完成", "已保存CSV。文件仅含数值与事件，不含摄像头画面。")
            except OSError as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def save_settings(self):
        if self.pipeline:
            QMessageBox.information(self, "设置", "请先结束当前会话并等待摄像头释放。")
            return
        candidate = Config(**asdict(self.config))
        candidate.camera = self.camera_input.value()
        candidate.hold = self.hold_input.value()
        candidate.sound = self.sound_input.isChecked()
        candidate.volume = self.volume_input.value()
        candidate.enter = {key: self.enter_inputs[key].value() for key in KEYS}
        candidate.exit = {key: self.exit_inputs[key].value() for key in KEYS}
        try:
            candidate.validate()
        except ValueError as error:
            QMessageBox.warning(self, "设置无效", str(error))
            return
        self.config = candidate
        self.store.save_settings(asdict(self.config))
        self.store.set_journey_enabled(self.journey_input.isChecked())
        self.refresh_journey()
        QMessageBox.information(self, "设置", "设置已保存。")

    def clear_data(self):
        if self.pipeline:
            QMessageBox.information(self, "清除记录", "请先结束当前会话。")
            return
        if QMessageBox.question(self, "清除记录", "将永久删除本机全部会话记录，是否继续？") == QMessageBox.StandardButton.Yes:
            self.store.clear()
            self.refresh_reports()
            self.report.setText("会话记录已清除。")
            self.timeline.rows = []
            self.timeline.update()

    def closeEvent(self, event):
        self.finish_session()
        if self.pipeline:
            self.pipeline.stop()
            if self.pipeline.alive():
                self.status.setText("正在释放摄像头，请稍候关闭窗口。")
                event.ignore()
                QTimer.singleShot(250, self.close)
                return
        self.timer.stop()
        self.store.close()
        event.accept()
