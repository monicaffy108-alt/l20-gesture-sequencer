"""Force sensor helpers: per-finger pressure metrics and contact-triggered closure."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .joints import JOINT_NAMES

FINGERS = ("thumb", "index", "middle", "ring", "pinky")

# Joint indices owned by each finger, following JOINT_NAMES order.
FINGER_JOINTS = {
    "thumb": (0, 1, 2, 3),
    "index": (4, 5, 6),
    "middle": (7, 8, 9),
    "ring": (10, 11, 12),
    "pinky": (13, 14, 15),
}


@dataclass
class GraspConfig:
    target: str = "fist"
    steps: int = 20
    interval: float = 0.15
    threshold: int = 30
    fingers: tuple[str, ...] = field(default_factory=lambda: FINGERS)
    hold: float = 1.0

    @classmethod
    def from_dict(cls, data: dict) -> "GraspConfig":
        return cls(
            target=data.get("target", "fist"),
            steps=int(data.get("steps", 20)),
            interval=float(data.get("interval", 0.15)),
            threshold=int(data.get("threshold", 30)),
            fingers=tuple(data.get("fingers") or FINGERS),
            hold=float(data.get("hold", 1.0)),
        )


def flexion(angles, finger: str) -> float:
    """Normalised flexion of one finger: 0 = fully extended, 100 = fully flexed."""
    joints = [angles[i] for i in FINGER_JOINTS[finger]]
    return 100.0 - min(joints)


def baseline(metrics: dict[str, int], fingers) -> dict[str, int]:
    return {finger: metrics[finger] for finger in fingers}


def contact(metrics: dict[str, int], base: dict[str, int], threshold: int) -> tuple[str, int] | None:
    """Return the first finger whose pressure rose above threshold, else None."""
    for finger, value in metrics.items():
        if finger not in base:
            continue
        delta = value - base[finger]
        if delta >= threshold:
            return finger, delta
    return None


def close_until_contact(hand, start, target, config: GraspConfig, dry_run: bool = False) -> dict:
    """Close the hand step by step, stopping as soon as a monitored finger touches.

    Returns a dict with the outcome: contacted finger, its pressure delta,
    closure ratio reached, and the command that was sent.
    """
    base = baseline(hand.read_force(), config.fingers)
    current = list(start)

    hit = None
    ratio = 0.0
    for step in range(1, config.steps + 1):
        ratio = step / config.steps
        current = [s + (t - s) * ratio for s, t in zip(start, target)]
        hand.set_angles(current)
        time.sleep(config.interval)

        metrics = hand.read_force()
        hit = contact(metrics, base, config.threshold)
        if hit:
            break

    result = {
        "finger": hit[0] if hit else None,
        "delta": hit[1] if hit else 0,
        "ratio": ratio,
        "angles": list(current),
        "baseline": base,
    }

    if hit:
        # Back off one step so the object is held, not crushed.
        back = max(0.0, ratio - 1.0 / config.steps)
        hand.set_angles([s + (t - s) * back for s, t in zip(start, target)])
    return result
