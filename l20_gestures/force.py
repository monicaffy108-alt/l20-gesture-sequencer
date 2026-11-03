"""Contact detection for the L20: pressure, torque, or position tracking error."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

FINGERS = ("thumb", "index", "middle", "ring", "pinky")

# Joint indices owned by each finger, following JOINT_NAMES order.
FINGER_JOINTS = {
    "thumb": (0, 1, 2, 3),
    "index": (4, 5, 6),
    "middle": (7, 8, 9),
    "ring": (10, 11, 12),
    "pinky": (13, 14, 15),
}

SOURCES = ("force", "torque", "angle_error")


@dataclass
class GraspConfig:
    target: str = "fist"
    source: str = "angle_error"
    steps: int = 20
    interval: float = 0.15
    # force: raw pressure delta (0-255 scale)
    threshold: float = 30.0
    # torque: delta in the SDK's 0-100 units
    torque_threshold: float = 15.0
    # angle_error: degrees of lag between commanded and measured angle
    tolerance: float = 12.0
    fingers: tuple[str, ...] = field(default_factory=lambda: FINGERS)
    hold: float = 1.0

    @classmethod
    def from_dict(cls, data: dict) -> "GraspConfig":
        return cls(
            target=data.get("target", "fist"),
            source=data.get("source", "angle_error"),
            steps=int(data.get("steps", 20)),
            interval=float(data.get("interval", 0.15)),
            threshold=float(data.get("threshold", 30.0)),
            torque_threshold=float(data.get("torque_threshold", 15.0)),
            tolerance=float(data.get("tolerance", 12.0)),
            fingers=tuple(data.get("fingers") or FINGERS),
            hold=float(data.get("hold", 1.0)),
        )


def flexion(angles, finger: str) -> float:
    """Normalised flexion of one finger: 0 = fully extended, 100 = fully flexed."""
    return 100.0 - min(angles[i] for i in FINGER_JOINTS[finger])


def finger_max(values, finger: str) -> float:
    return max(values[i] for i in FINGER_JOINTS[finger])


def torque_metrics(torques) -> dict[str, float]:
    return {finger: finger_max(torques, finger) for finger in FINGERS}


def tracking_error(commanded, measured) -> dict[str, float]:
    """Per-finger lag between the commanded and measured joint angles."""
    return {
        finger: max(
            abs(commanded[i] - measured[i]) for i in FINGER_JOINTS[finger]
        )
        for finger in FINGERS
    }


def baseline(metrics: dict[str, float], fingers) -> dict[str, float]:
    return {finger: metrics[finger] for finger in fingers}


def delta_contact(metrics, base, threshold: float):
    """Return the first finger whose value rose above threshold, else None."""
    for finger, value in metrics.items():
        if finger not in base:
            continue
        delta = value - base[finger]
        if delta >= threshold:
            return finger, delta
    return None


def absolute_contact(metrics, fingers, threshold: float):
    for finger in fingers:
        if metrics[finger] >= threshold:
            return finger, metrics[finger]
    return None


def read_metric(hand, source: str, commanded=None):
    if source == "force":
        return hand.read_force()
    if source == "torque":
        return torque_metrics(hand.read_torque())
    return tracking_error(commanded, hand.read_angles())


def close_until_contact(hand, start, target, config: GraspConfig) -> dict:
    """Close the hand step by step, stopping as soon as contact is detected.

    Detects contact from pressure, joint torque, or position tracking error.
    Returns the finger that touched, the metric delta, the closure ratio and
    the command that was sent.
    """
    source = config.source
    base = None
    if source in ("force", "torque"):
        base = baseline(read_metric(hand, source, start), config.fingers)

    hit = None
    ratio = 0.0
    current = list(start)
    for step in range(1, config.steps + 1):
        ratio = step / config.steps
        current = [s + (t - s) * ratio for s, t in zip(start, target)]
        hand.set_angles(current)
        time.sleep(config.interval)

        metrics = read_metric(hand, source, current)
        if source == "force":
            hit = delta_contact(metrics, base, config.threshold)
        elif source == "torque":
            hit = delta_contact(metrics, base, config.torque_threshold)
        else:
            hit = absolute_contact(metrics, config.fingers, config.tolerance)
        if hit:
            break

    result = {
        "finger": hit[0] if hit else None,
        "value": hit[1] if hit else 0,
        "ratio": ratio,
        "angles": list(current),
        "source": source,
    }

    if hit:
        # Back off one step so the object is held, not crushed.
        back = max(0.0, ratio - 1.0 / config.steps)
        hand.set_angles([s + (t - s) * back for s, t in zip(start, target)])
    return result
