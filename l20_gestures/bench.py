"""Hardware benchmarks: repeatability, step response and tracking error.

Every number printed here comes from the encoded position or the pressure
sensors, so the results can be quoted as measured values rather than claims.
"""

from __future__ import annotations

import statistics
import time

from .force import GraspConfig, close_until_contact
from .joints import JOINT_NAMES, NUM_JOINTS
from .sequence import SequenceConfig, move_to


def _fmt(values, digits: int = 1) -> str:
    return " ".join(f"{v:{digits + 3}.{digits}f}" for v in values)


def _current(hand, fallback) -> list[float]:
    """Encoder values, or the fallback when the backend has no reading yet."""
    values = list(hand.read_angles())
    if any(value != value for value in values):  # NaN before the first command
        return list(fallback)
    return values


def grasp_trials(hand, gestures: dict, config: GraspConfig, seq_cfg: SequenceConfig,
                 trials: int) -> None:
    """Repeat the closed-loop grasp and report how often it actually holds.

    A trial counts as a contact when any finger crosses the threshold, and as a
    hold when the fingers are still loaded after the one-step back-off.
    """
    start = list(gestures["open"]["angles"])
    target = list(gestures[config.target]["angles"])
    fingers = tuple(config.fingers)

    contacts = holds = 0
    ratios = []
    peaks = []

    print(f"Grasp repeatability: {trials} trials, target '{config.target}', "
          f"source '{config.source}', threshold {config.threshold}\n")
    print("Hold the object against the palm each time the hand re-opens.\n")

    for trial in range(1, trials + 1):
        move_to(hand, start, _current(hand, start), seq_cfg.transition, seq_cfg.fps)
        time.sleep(1.2)

        result = close_until_contact(hand, start, target, config)
        contact = bool(result["finger"])

        held = False
        if contact:
            time.sleep(0.3)
            peak = max(hand.read_force()[finger] for finger in fingers)
            peaks.append(peak)
            held = peak >= config.threshold
            ratios.append(result["ratio"] * 100.0)

        contacts += int(contact)
        holds += int(held)
        status = "hold" if held else ("contact" if contact else "miss")
        print(f"  trial {trial:2d}/{trials}  {status:8s} "
              f"finger={str(result['finger']):8s} "
              f"value={result['value']:6.1f}  "
              f"closure={result['ratio'] * 100.0:5.1f}%")

    print(f"\n  contact detected : {contacts}/{trials} "
          f"({contacts / trials * 100:.0f}%)")
    print(f"  object held      : {holds}/{trials} "
          f"({holds / trials * 100:.0f}%)")
    if ratios:
        print(f"  closure at contact: mean {statistics.mean(ratios):.1f}% "
              f"sd {statistics.stdev(ratios) if len(ratios) > 1 else 0.0:.1f}")
    if peaks:
        print(f"  pressure after back-off: mean {statistics.mean(peaks):.1f} "
              f"(threshold {config.threshold})")


def step_response(hand, joint: str, low: float = 0.0, high: float = 100.0,
                  repeats: int = 3) -> None:
    """Drive one joint as a step and time how long the encoder takes to follow."""
    if joint not in JOINT_NAMES:
        raise SystemExit(f"unknown joint {joint}; available: {', '.join(JOINT_NAMES)}")
    index = JOINT_NAMES.index(joint)
    samples = []
    period = 1.0 / 60.0

    def command(value: float, seconds: float = 0.0) -> None:
        angles = _current(hand, [50.0] * NUM_JOINTS)
        angles[index] = value
        hand.set_angles(angles)
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            hand.set_angles(angles)
            time.sleep(period)

    print(f"Step response: {joint} {low:.0f} -> {high:.0f}, {repeats} repeats\n")

    for repeat in range(1, repeats + 1):
        command(low, 0.8)
        start = time.monotonic()
        command(high)

        target = high - low
        t63 = t90 = None
        while time.monotonic() - start < 3.0:
            measured = float(hand.read_angles()[index])
            elapsed = time.monotonic() - start
            reached = (measured - low) / target
            if t63 is None and reached >= 0.63:
                t63 = elapsed
            if reached >= 0.90:
                t90 = elapsed
                break
            time.sleep(period)

        samples.append(t90 if t90 is not None else 3.0)
        print(f"  repeat {repeat}: t63={t63 * 1000 if t63 else float('nan'):6.0f} ms  "
              f"t90={t90 * 1000 if t90 else float('nan'):6.0f} ms  "
              f"final={measured:5.1f}")

    print(f"\n  t90 mean {statistics.mean(samples) * 1000:.0f} ms, "
          f"sd {(statistics.stdev(samples) if len(samples) > 1 else 0.0) * 1000:.0f} ms")


def tracking_error(hand, gestures: dict, seq_cfg: SequenceConfig,
                   settle: float = 0.8) -> None:
    """Command each gesture, wait for it to settle, then compare command to encoder."""
    rows = []
    print(f"Tracking error: settled position vs command, {len(gestures)} gestures\n")
    print("  gesture      mean   max   worst joint")

    for name, data in gestures.items():
        target = list(data["angles"])
        move_to(hand, target, _current(hand, target), seq_cfg.transition, seq_cfg.fps)
        time.sleep(settle)
        measured = list(hand.read_angles())

        errors = [abs(m - t) for m, t in zip(measured, target)]
        mean = statistics.mean(errors)
        worst = max(errors)
        index = errors.index(worst)
        rows.append(errors)
        print(f"  {name:12s} {mean:5.1f} {worst:5.1f}   {JOINT_NAMES[index]}")

    flat = [value for row in rows for value in row]
    rms = (sum(value * value for value in flat) / len(flat)) ** 0.5
    print(f"\n  RMS over all joints and gestures: {rms:.1f}")
    print(f"  mean absolute error: {statistics.mean(flat):.1f}")


def run(hand, gestures: dict, what: str, *, config: GraspConfig,
        seq_cfg: SequenceConfig, trials: int, joint: str) -> None:
    if what in ("grasp", "all"):
        grasp_trials(hand, gestures, config, seq_cfg, trials)
        print()
    if what in ("step", "all"):
        step_response(hand, joint)
        print()
    if what in ("tracking", "all"):
        tracking_error(hand, gestures, seq_cfg)
