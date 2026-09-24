from types import SimpleNamespace
import math
import numpy as np
import pytest
from zuoban.vision import rotation_angles, shoulder_geometry, Latest


@pytest.mark.parametrize("degrees", [-25, -10, 0, 15, 30])
def test_pitch_sign_and_scaled_rotation(degrees):
    a = math.radians(degrees)
    rotation = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation * 1.2
    pitch, yaw, roll = rotation_angles(matrix)
    assert pitch == pytest.approx(degrees)
    assert yaw == pytest.approx(0)
    assert roll == pytest.approx(0)


def test_pixel_aspect_and_ratio_scale_invariance():
    left = SimpleNamespace(x=0.25, y=0.4)
    right = SimpleNamespace(x=0.75, y=0.6)
    nose = SimpleNamespace(x=0.5, y=0.2)
    angle, ratio = shoulder_geometry(left, right, nose, 640, 480)
    angle2, ratio2 = shoulder_geometry(right, left, nose, 1280, 960)
    assert angle == pytest.approx(math.degrees(math.atan2(96, 320)))
    assert angle2 == pytest.approx(angle)
    assert ratio2 == pytest.approx(ratio)


def test_latest_frame_replaces_pending():
    mailbox = Latest()
    for i in range(100):
        mailbox.put(i)
    assert mailbox.get() == (100, 99)
