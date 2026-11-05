"""Hand teleoperation: camera + MediaPipe landmarks -> 16 L20 joints.

The camera observes a human hand, MediaPipe returns 21 landmarks, and the
landmark geometry is turned into the same 0-100 joint space the rest of this
package uses (100 = fully extended, 0 = fully flexed).

Landmarks are normalized to [0, 1], so the mapping is scale invariant. The
constants below are the only tuning knobs.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

try:  # Windows console keyboard polling; absent on Linux/macOS
    import msvcrt as _MSVCRT
except ImportError:
    _MSVCRT = None

from .config import ROOT
from .joints import JOINT_NAMES, NUM_JOINTS, validate

DEFAULT_MODEL = ROOT / "assets" / "models" / "hand_landmarker.task"

# MediaPipe hand landmark indices
WRIST = 0
THUMB = (1, 2, 3, 4)
INDEX = (5, 6, 7, 8)
MIDDLE = (9, 10, 11, 12)
RING = (13, 14, 15, 16)
PINKY = (17, 18, 19, 20)
FINGERS = {"index": INDEX, "middle": MIDDLE, "ring": RING, "pinky": PINKY}

LANDMARK_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (5, 9), (9, 10), (10, 11), (11, 12),
    (9, 13), (13, 14), (14, 15), (15, 16),
    (13, 17), (17, 18), (18, 19), (19, 20),
    (0, 17),
)

# A straight finger measures close to 180 deg between consecutive landmarks;
# a closed fist measures well under 100 deg in the 2D projection.
FLEX_STRAIGHT_DEG = 180.0
FLEX_BENT_DEG = 75.0

ABD_GAIN = 2.5
ABD_CENTER = 50.0

THUMB_SPREAD_MIN_DEG = 20.0
THUMB_SPREAD_MAX_DEG = 70.0


def _angle(a, b, c) -> float:
    """Angle at ``b`` formed by the points ``a-b-c``, in degrees."""
    v1 = (a[0] - b[0], a[1] - b[1])
    v2 = (c[0] - b[0], c[1] - b[1])
    n1 = math.hypot(*v1)
    n2 = math.hypot(*v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 180.0
    dot = (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def _signed_spread(origin, reference, point) -> float:
    """Degrees from ``reference`` to ``point`` around ``origin``, signed by side."""
    ref = (reference[0] - origin[0], reference[1] - origin[1])
    vec = (point[0] - origin[0], point[1] - origin[1])
    n_ref = math.hypot(*ref)
    n_vec = math.hypot(*vec)
    if n_ref < 1e-6 or n_vec < 1e-6:
        return 0.0
    dot = (ref[0] * vec[0] + ref[1] * vec[1]) / (n_ref * n_vec)
    angle = math.degrees(math.acos(max(-1.0, min(1.0, dot))))
    cross = ref[0] * vec[1] - ref[1] * vec[0]
    return -angle if cross < 0 else angle


def _flex_to_value(angle_deg: float) -> float:
    """Map a measured joint angle to 0-100, where 100 is fully extended."""
    span = FLEX_STRAIGHT_DEG - FLEX_BENT_DEG
    value = (angle_deg - FLEX_BENT_DEG) / span * 100.0
    return max(0.0, min(100.0, value))


def landmarks_to_joints(points) -> list[float]:
    """Convert 21 normalized landmarks into the 16 L20 joint values."""
    values = [0.0] * NUM_JOINTS

    # Thumb: abd, yaw, root1, tip.
    spread = _signed_spread(points[WRIST], points[INDEX[0]], points[THUMB[0]])
    opening = (abs(spread) - THUMB_SPREAD_MIN_DEG) / (
        THUMB_SPREAD_MAX_DEG - THUMB_SPREAD_MIN_DEG
    ) * 100.0
    values[0] = max(0.0, min(100.0, opening))
    values[1] = _flex_to_value(_angle(points[WRIST], points[THUMB[0]], points[THUMB[1]]))
    values[2] = _flex_to_value(_angle(points[THUMB[0]], points[THUMB[1]], points[THUMB[2]]))
    values[3] = _flex_to_value(_angle(points[THUMB[1]], points[THUMB[2]], points[THUMB[3]]))

    # Four long fingers: abd, root1, tip.
    # root1 is the MCP joint (palm -> proximal phalanx), tip is the PIP joint
    # (proximal -> middle phalanx). The DIP joint is the URDF mimic and is not
    # measured separately.
    # 2D projection foreshortens MCP rotation, so root1 takes the smaller of the
    # MCP and PIP estimates: whichever joint is most bent drives the command.
    middle_mcp = points[MIDDLE[0]]
    for offset, name in enumerate(("index", "middle", "ring", "pinky")):
        mcp, pip, dip, _tip = FINGERS[name]
        base = 4 + offset * 3
        mcp_flex = _flex_to_value(_angle(points[WRIST], points[mcp], points[pip]))
        pip_flex = _flex_to_value(_angle(points[mcp], points[pip], points[dip]))
        values[base + 1] = min(mcp_flex, pip_flex)
        values[base + 2] = pip_flex
        # Lateral spread is only meaningful while the finger is extended: once it
        # curls towards the camera the projected knuckles collapse onto each other
        # and the measured angle runs to 0 or 100. Fade it out with flexion so a
        # closed fist lands on neutral abduction instead of a random extreme.
        extension = pip_flex / 100.0
        lateral = _signed_spread(points[WRIST], middle_mcp, points[mcp])
        raw_abd = max(0.0, min(100.0, ABD_CENTER + ABD_GAIN * lateral))
        values[base] = ABD_CENTER + (raw_abd - ABD_CENTER) * extension
    return validate(values)


class Smoother:
    """Exponential moving average with a per-update change limit."""

    def __init__(self, alpha: float = 0.5, max_step: float = 6.0):
        self.alpha = alpha
        self.max_step = max_step
        self._state: list[float] | None = None

    def reset(self, values) -> None:
        self._state = list(values)

    def update(self, values) -> list[float]:
        values = list(values)
        if self._state is None:
            self._state = values
            return list(values)
        out = []
        for previous, new in zip(self._state, values):
            blended = previous + self.alpha * (new - previous)
            delta = max(-self.max_step, min(self.max_step, blended - previous))
            out.append(previous + delta)
        self._state = out
        return list(out)


class HandLandmarker:
    """Thin wrapper over the MediaPipe Tasks hand landmarker."""

    def __init__(self, model_path: Path | str = DEFAULT_MODEL, num_hands: int = 1):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        if not Path(model_path).exists():
            raise FileNotFoundError(
                f"hand landmark model not found: {model_path}\n"
                "Download it with:\n"
                "  curl -L -o assets/models/hand_landmarker.task "
                "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
                "hand_landmarker/float16/1/hand_landmarker.task"
            )

        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._mp = mp
        self._landmarker = vision.HandLandmarker.create_from_options(options)

    def detect(self, rgb_frame, timestamp_ms: int):
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb_frame)
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        if not result.hand_landmarks:
            return None
        return [(lm.x, lm.y) for lm in result.hand_landmarks[0]]

    def close(self) -> None:
        self._landmarker.close()


class Camera:
    """RealSense color stream with a plain webcam fallback."""

    def __init__(self, backend: str = "realsense", device_id: int = 0,
                 width: int = 640, height: int = 480, fps: int = 30):
        self.backend = backend
        self._pipeline = None
        self._capture = None
        self.width = width
        self.height = height

        if backend == "realsense":
            import pyrealsense2 as rs

            self._pipeline = rs.pipeline()
            config = rs.config()
            config.enable_stream(rs.stream.color, width, height, rs.format.bgr8, fps)
            self._pipeline.start(config)
            for _ in range(10):  # let auto-exposure settle
                self._pipeline.wait_for_frames()
        else:
            import cv2

            self._capture = cv2.VideoCapture(device_id, cv2.CAP_DSHOW)
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            if not self._capture.isOpened():
                raise RuntimeError(f"cannot open camera index {device_id}")

    def read(self):
        if self._pipeline is not None:
            frames = self._pipeline.wait_for_frames()
            color = frames.get_color_frame()
            if not color:
                return None
            return np.asanyarray(color.get_data()).copy()

        import cv2

        ok, frame = self._capture.read()
        return frame if ok else None

    def close(self) -> None:
        if self._pipeline is not None:
            self._pipeline.stop()
        if self._capture is not None:
            self._capture.release()


def draw_overlay(frame, points, values, lost: bool = False):
    """Draw landmarks, a per-joint bar panel, and a status line."""
    import cv2

    height, width = frame.shape[:2]
    if points:
        pixels = [(int(x * width), int(y * height)) for x, y in points]
        for a, b in LANDMARK_CONNECTIONS:
            cv2.line(frame, pixels[a], pixels[b], (0, 200, 0), 2, cv2.LINE_AA)
        for point in pixels:
            cv2.circle(frame, point, 3, (0, 0, 255), -1, cv2.LINE_AA)

    panel_width = 210
    canvas = np.zeros((height, width + panel_width, 3), dtype=np.uint8)
    canvas[:, :width] = frame
    for index, (name, value) in enumerate(zip(JOINT_NAMES, values)):
        y = 8 + index * 28
        cv2.putText(canvas, name, (width + 8, y + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1, cv2.LINE_AA)
        cv2.rectangle(canvas, (width + 96, y), (width + 96 + int(value * 0.95), y + 14),
                      (60, 180, 255), -1)
        cv2.putText(canvas, f"{value:5.1f}", (width + 96, y + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255, 255, 255), 1, cv2.LINE_AA)
    if lost:
        cv2.putText(canvas, "no hand detected - holding last pose", (12, height - 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
    return canvas


def _quit_pressed(preview: bool) -> bool:
    """True when q was pressed in the preview window or typed in the terminal.

    ``cv2.waitKey`` only sees keys while the OpenCV window owns the keyboard
    focus, so hitting q from the terminal would otherwise be ignored.
    """
    import cv2

    if preview and (cv2.waitKey(1) & 0xFF) == ord("q"):
        return True
    if _MSVCRT is not None and _MSVCRT.kbhit():
        if _MSVCRT.getwch() in ("q", "Q", "\x1b"):
            return True
    return False


def run_teleop(hand, *, backend: str = "realsense", device_id: int = 0,
               model_path=DEFAULT_MODEL, alpha: float = 0.5, max_step: float = 6.0,
               mirror: bool = True, preview: bool = True, duration: float | None = None,
               fps_limit: float = 30.0, start_pose: list[float] | None = None) -> None:
    """Live loop: camera -> landmarks -> joints -> hand."""
    import cv2

    smoother = Smoother(alpha=alpha, max_step=max_step)
    held = list(start_pose) if start_pose is not None else [50.0] * NUM_JOINTS
    smoother.reset(held)

    camera = Camera(backend=backend, device_id=device_id)
    tracker = HandLandmarker(model_path)
    lost = False
    started = time.monotonic()
    last_send = 0.0

    try:
        while True:
            frame = camera.read()
            if frame is None:
                continue
            if mirror:
                frame = cv2.flip(frame, 1)

            points = tracker.detect(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                                    int(time.monotonic() * 1000) % 2_000_000_000)
            lost = points is None
            if points is not None:
                held = smoother.update(landmarks_to_joints(points))

            now = time.monotonic()
            if now - last_send >= 1.0 / fps_limit:
                hand.set_angles(held)
                last_send = now

            if preview:
                cv2.imshow("L20 teleop - q to quit", draw_overlay(frame, points, held, lost))
            if _quit_pressed(preview):
                break

            if duration is not None and now - started >= duration:
                break
    finally:
        tracker.close()
        camera.close()
        if preview:
            cv2.destroyAllWindows()
