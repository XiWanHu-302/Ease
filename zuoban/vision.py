"""CPU推理与最新帧邮箱；原始画面推理，镜像只发生在显示时。"""
from dataclasses import dataclass
from pathlib import Path
import math
import threading
import time

import cv2
import numpy as np

from .core import Measurement, KEYS


def rotation_angles(matrix):
    """右手系、Y向上。R=Rz(roll) Ry(yaw) Rx(pitch)，正pitch朝下。

    极分解移除尺度；此角度是相机坐标中的模型估计，不是临床测量。
    """
    m = np.asarray(matrix, dtype=float)[:3, :3]
    if not np.isfinite(m).all():
        raise ValueError("非有限人脸变换矩阵")
    u, _, vt = np.linalg.svd(m)
    r = u @ vt
    if np.linalg.det(r) < 0:
        u[:, -1] *= -1
        r = u @ vt
    pitch = math.atan2(r[2, 1], r[2, 2])
    yaw = math.atan2(-r[2, 0], math.hypot(r[0, 0], r[1, 0]))
    roll = math.atan2(r[1, 0], r[0, 0])
    return tuple(math.degrees(a) for a in (pitch, yaw, roll))


def shoulder_geometry(left, right, nose, width, height):
    """left/right为模型解剖标签；排序后在原始像素平面量肩线倾角。"""
    a, b = sorted(((left.x * width, left.y * height), (right.x * width, right.y * height)))
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = math.hypot(dx, dy)
    if span < width * 0.10:
        raise ValueError("肩部太小或侧转过大")
    angle = math.degrees(math.atan2(dy, dx))
    ratio = None
    if nose is not None:
        nx, ny = nose.x * width, nose.y * height
        ratio = abs(dx * (ny - a[1]) - dy * (nx - a[0])) / (span * span)
    return angle, ratio


class Detector:
    def __init__(self, model_dir):
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        self.mp = mp
        self.face = self.pose = None
        self.last_ms = -1
        base = mp.tasks.BaseOptions
        self.paths = {name: Path(model_dir) / f"{name}.task" for name in ("face_landmarker", "pose_landmarker_lite")}
        for path in self.paths.values():
            if not path.is_file():
                raise FileNotFoundError(f"模型缺失：{path.name}。请先运行模型下载脚本。")
        try:
            self.face = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
                base_options=base(model_asset_buffer=self.paths["face_landmarker"].read_bytes(), delegate=base.Delegate.CPU),
                running_mode=vision.RunningMode.VIDEO, num_faces=1,
                min_face_detection_confidence=0.6, min_face_presence_confidence=0.6,
                min_tracking_confidence=0.6, output_facial_transformation_matrixes=True))
            self.pose = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
                base_options=base(model_asset_buffer=self.paths["pose_landmarker_lite"].read_bytes(), delegate=base.Delegate.CPU),
                running_mode=vision.RunningMode.VIDEO, num_poses=1,
                min_pose_detection_confidence=0.6, min_pose_presence_confidence=0.6,
                min_tracking_confidence=0.6, output_segmentation_masks=False))
        except Exception:
            self.close()
            raise

    def detect(self, frame, timestamp):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
        ms = max(self.last_ms + 1, int(timestamp * 1000))
        self.last_ms = ms
        face = self.face.detect_for_video(image, ms)
        pose = self.pose.detect_for_video(image, ms)
        values = dict.fromkeys(KEYS)
        reasons = {"pitch": "未检测到清晰正面人脸", "roll": "未检测到清晰正面人脸", "shoulder": "请让双肩完整入镜"}
        yaw = ratio = None
        points, lines = [], []
        height, width = frame.shape[:2]
        if face.facial_transformation_matrixes and face.face_landmarks:
            landmarks = face.face_landmarks[0]
            selected = [landmarks[i] for i in (1, 33, 263, 61, 291, 152)]
            if all(0.01 <= p.x <= 0.99 and 0.01 <= p.y <= 0.99 for p in selected):
                pitch, yaw, roll = rotation_angles(face.facial_transformation_matrixes[0])
                values.update(pitch=pitch, roll=roll)
                reasons.pop("pitch", None)
                reasons.pop("roll", None)
                points.extend((int(p.x * width), int(p.y * height)) for p in selected)
        if pose.pose_landmarks:
            landmarks = pose.pose_landmarks[0]
            shoulders = [landmarks[11], landmarks[12]]
            if all(p.visibility >= 0.65 and p.presence >= 0.65 and 0.02 < p.x < 0.98 and 0.02 < p.y < 0.98 for p in shoulders):
                try:
                    nose = landmarks[0] if landmarks[0].visibility >= 0.65 else None
                    values["shoulder"], ratio = shoulder_geometry(*shoulders, nose, width, height)
                    reasons.pop("shoulder", None)
                    ends = [(int(p.x * width), int(p.y * height)) for p in shoulders]
                    points.extend(ends)
                    lines.append(ends)
                except ValueError as e:
                    reasons["shoulder"] = str(e)
        overlay = frame.copy()
        for a, b in lines:
            cv2.line(overlay, a, b, (180, 225, 80), 2, cv2.LINE_AA)
        for p in points:
            cv2.circle(overlay, p, 4, (130, 235, 65), -1, cv2.LINE_AA)
        return Measurement(timestamp, values, reasons, yaw, ratio), overlay

    def close(self):
        for name in ("face", "pose"):
            task = getattr(self, name, None)
            if task is not None:
                task.close()
                setattr(self, name, None)


class Latest:
    def __init__(self):
        self.lock = threading.Lock()
        self.value = None
        self.serial = 0

    def put(self, value):
        with self.lock:
            self.value = value
            self.serial += 1

    def get(self):
        with self.lock:
            return self.serial, self.value


@dataclass
class Packet:
    measurement: Measurement
    frame: object
    latency_ms: float


class Pipeline:
    def __init__(self, camera, model_dir):
        self.camera, self.model_dir = camera, model_dir
        self.frames, self.results = Latest(), Latest()
        self.stop_event = threading.Event()
        self.error = None
        self.status = "正在加载模型与摄像头…"
        self.threads = []

    def start(self):
        self.threads = [threading.Thread(target=self._capture, daemon=True, name="camera"),
                        threading.Thread(target=self._infer, daemon=True, name="inference")]
        for thread in self.threads:
            thread.start()

    def _capture(self):
        cap = None
        try:
            cap = cv2.VideoCapture(self.camera, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap.release()
                cap = cv2.VideoCapture(self.camera)
            if not cap.isOpened():
                raise RuntimeError("无法打开摄像头，请检查Windows相机权限、摄像头编号或是否被其他软件占用。")
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            failures = 0
            while not self.stop_event.is_set():
                ok, frame = cap.read()
                stamp = time.monotonic()
                if not ok:
                    failures += 1
                    if failures >= 5:
                        raise RuntimeError("摄像头读取中断，请重新连接后启动。")
                    self.stop_event.wait(0.1)
                    continue
                failures = 0
                self.frames.put((stamp, frame))
        except Exception as e:
            self.error = str(e)
            self.stop_event.set()
        finally:
            if cap is not None:
                cap.release()

    def _infer(self):
        detector = None
        try:
            detector = Detector(self.model_dir)
            self.status = "请开始个人校准"
            seen = 0
            while not self.stop_event.is_set():
                started = time.monotonic()
                serial, item = self.frames.get()
                if item is not None and serial != seen:
                    seen = serial
                    stamp, frame = item
                    m, overlay = detector.detect(frame, stamp)
                    self.results.put(Packet(m, overlay, (time.monotonic() - stamp) * 1000))
                self.stop_event.wait(max(0.001, 0.1 - (time.monotonic() - started)))
        except Exception as e:
            self.error = f"模型推理失败：{e}"
            self.stop_event.set()
        finally:
            if detector is not None:
                detector.close()

    def stop(self):
        self.stop_event.set()

    def alive(self):
        return any(t.is_alive() for t in self.threads)
