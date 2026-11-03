"""Sequence layer: linear interpolation between gestures plus timed updates."""

from __future__ import annotations

import time
from dataclasses import dataclass

from .joints import NUM_JOINTS, validate

GESTURE_KEYS = ("open", "fist", "relax", "point", "thumbs_up", "ok", "pinch")


@dataclass
class SequenceConfig:
    fps: int = 25
    transition: float = 0.6
    hold: float = 0.8

    @classmethod
    def from_dict(cls, data: dict) -> "SequenceConfig":
        return cls(
            fps=int(data.get("fps", 25)),
            transition=float(data.get("transition", 0.6)),
            hold=float(data.get("hold", 0.8)),
        )


def blend(start: list[float], end: list[float], ratio: float) -> list[float]:
    ratio = max(0.0, min(1.0, ratio))
    return [s + (e - s) * ratio for s, e in zip(start, end)]


def move_to(hand, target, start, duration: float, fps: int) -> list[float]:
    """Move smoothly from start to target and return the end state."""
    steps = max(1, int(duration * fps))
    period = 1.0 / fps
    for step in range(1, steps + 1):
        hand.set_angles(blend(start, target, step / steps))
        time.sleep(period)
    return list(target)


def run_sequence(hand, gestures: dict, names: list[str], config: SequenceConfig, start=None) -> None:
    if not names:
        raise ValueError("empty sequence")

    missing = [name for name in names if name not in gestures]
    if missing:
        raise ValueError(f"unknown gestures: {missing}; available: {sorted(gestures)}")

    current = validate(start) if start is not None else [50.0] * NUM_JOINTS

    for index, name in enumerate(names, start=1):
        target = validate(gestures[name]["angles"])
        print(f"[{index}/{len(names)}] {name} - {gestures[name].get('desc', '')}")
        current = move_to(hand, target, current, config.transition, config.fps)
        time.sleep(config.hold)

    return current
