"""旅程地图与带日期标记的日历控件。"""
from math import cos, pi, sin

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QCalendarWidget, QWidget

from .journey import STATIONS


class JourneyMap(QWidget):
    def __init__(self):
        super().__init__()
        self.completed = 0
        self.current = 1
        self.enabled = True
        self.setMinimumSize(410, 265)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FBF6EC"))
        width = self.width()
        centers = [QPointF(40 + i * (width - 80) / 6, 105 + (28 if i % 2 else -5)) for i in range(7)]
        path = QPainterPath(centers[0])
        for center in centers[1:]:
            path.lineTo(center)
        painter.setPen(QPen(QColor("#D9DED3"), 5, Qt.PenStyle.DashLine))
        painter.drawPath(path)
        for i, center in enumerate(centers):
            done = i < self.completed
            current = i + 1 == self.current
            fill = QColor("#17655D" if done else "#F4C19F" if current else "#E7E7DF")
            if not self.enabled:
                fill = QColor("#E7E7DF")
            painter.setPen(QPen(QColor("#17655D") if current and self.enabled else QColor("#D4D7D0"), 2))
            painter.setBrush(fill)
            painter.drawEllipse(center, 29, 29)
            painter.setPen(QColor("#FFFFFF" if done else "#29433E"))
            painter.drawText(QRectF(center.x()-27, center.y()-18, 54, 36), Qt.AlignmentFlag.AlignCenter,
                             "✓" if done else str(i + 1))
            painter.setPen(QColor("#31524B" if done or current else "#89928A"))
            painter.drawText(QRectF(center.x()-34, center.y()+37, 68, 27), Qt.AlignmentFlag.AlignCenter,
                             STATIONS[i][0])
            self._scene(painter, center.x(), center.y()+83, i, done or current)

    @staticmethod
    def _scene(painter, x, y, index, visible):
        if not visible:
            return
        painter.setPen(QPen(QColor("#A46D52"), 2))
        painter.setBrush(QColor("#E7B18E"))
        if index == 0:  # 晨光
            painter.drawEllipse(QPointF(x, y), 12, 12)
        elif index == 1:  # 书桌上的书
            painter.drawRect(QRectF(x-16, y-9, 32, 19))
            painter.drawLine(QPointF(x, y-9), QPointF(x, y+10))
        elif index == 2:  # 林间
            painter.drawPolygon(QPolygonF([QPointF(x, y-16), QPointF(x-15, y+11), QPointF(x+15, y+11)]))
        elif index == 3:  # 石桥
            painter.drawArc(QRectF(x-18, y-7, 36, 26), 0, 180*16)
            painter.drawLine(QPointF(x-20, y+7), QPointF(x+20, y+7))
        elif index == 4:  # 山坡
            painter.drawPolygon(QPolygonF([QPointF(x-19, y+11), QPointF(x, y-15), QPointF(x+19, y+11)]))
        elif index == 5:  # 灯塔
            painter.drawRect(QRectF(x-8, y-10, 16, 22))
            painter.drawEllipse(QPointF(x, y-13), 5, 5)
        else:  # 星空
            vertices = [QPointF(x + (16 if i % 2 == 0 else 7)*cos(-pi/2+i*pi/5),
                               y + (16 if i % 2 == 0 else 7)*sin(-pi/2+i*pi/5)) for i in range(10)]
            painter.drawPolygon(QPolygonF(vertices))


class UsageCalendar(QCalendarWidget):
    def __init__(self):
        super().__init__()
        self.days = {}
        self.setGridVisible(False)
        self.setFirstDayOfWeek(Qt.DayOfWeek.Monday)
        self.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)

    def paintCell(self, painter, rect, date):
        super().paintCell(painter, rect, date)
        info = self.days.get(date.toString("yyyy-MM-dd"))
        if not info:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#D78968" if info["completed"] else "#17655D"))
        center = QPointF(rect.center().x(), rect.bottom()-6)
        if info["completed"]:
            painter.drawPolygon(QPolygonF([QPointF(center.x(),center.y()-4),
                                           QPointF(center.x()+4,center.y()),
                                           QPointF(center.x(),center.y()+4),
                                           QPointF(center.x()-4,center.y())]))
        else:
            painter.drawEllipse(center, 3, 3)
        painter.restore()
