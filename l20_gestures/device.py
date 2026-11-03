"""Device layer: a thin wrapper around the linkerbot SDK.

The SDK is imported lazily, so dry-run keeps working without linkerbot
installed or without hardware attached.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from .force import FINGERS, flexion
from .joints import JOINT_NAMES, NUM_JOINTS, validate


@dataclass
class DeviceConfig:
    side: str = "left"
    interface_type: str = "pcan"
    interface_name: str = "PCAN_USBBUS1"

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceConfig":
        return cls(
            side=data.get("side", "left"),
            interface_type=data.get("interface_type", "pcan"),
            interface_name=data.get("interface_name", "PCAN_USBBUS1"),
        )


class DryRunHand:
    """Prints commands instead of talking to hardware. Used to check sequences."""

    def __init__(self, config: DeviceConfig):
        self.config = config
        self._last: list[float] = [float("nan")] * NUM_JOINTS

    def __enter__(self) -> "DryRunHand":
        print(
            f"[dry-run] side={self.config.side} "
            f"interface={self.config.interface_type}:{self.config.interface_name}"
        )
        return self

    def __exit__(self, *exc) -> None:
        pass

    def set_angles(self, angles) -> None:
        self._last = validate(angles)
        text = " ".join(f"{name}={value:5.1f}" for name, value in zip(JOINT_NAMES, self._last))
        print(f"[dry-run] {text}")

    def read_angles(self) -> list[float]:
        # Simulated obstacle: joints cannot close past 45 degrees.
        return [max(value, 45.0) if value == value else value for value in self._last]

    def read_torque(self) -> list[float]:
        return [round(max(0.0, (100.0 - value) if value == value else 0.0) * 0.5, 1)
                for value in self._last]

    def read_force(self) -> dict[str, int]:
        """Synthetic pressure: a finger starts reading non-zero at 30% flexion."""
        if any(value != value for value in self._last):  # NaN before the first command
            return {finger: 0 for finger in FINGERS}
        return {
            finger: min(255, max(0, int((flexion(self._last, finger) - 30) * 3)))
            for finger in FINGERS
        }

    def read_force_matrices(self) -> dict:
        return {finger: None for finger in FINGERS}


class LinkerHand:
    """Real hardware backend, wrapping linkerbot.L25."""

    def __init__(self, config: DeviceConfig):
        self.config = config
        self._hand = None

    def __enter__(self) -> "LinkerHand":
        try:
            from linkerbot import L25
        except ImportError as exc:  # pragma: no cover - depends on the local env
            raise SystemExit(
                "linkerbot SDK not found. Install it first: pip install linkerbot\n"
                "To check sequence logic without hardware, add --dry-run."
            ) from exc

        try:
            self._hand = L25(
                side=self.config.side,
                interface_name=self.config.interface_name,
                interface_type=self.config.interface_type,
            )
            self._hand.__enter__()
        except Exception as exc:
            raise SystemExit(
                f"connection failed: {exc}\n"
                "Checklist:\n"
                "  1. Close every program using the CAN adapter "
                "(vendor GUI, PCAN-View, browser control panel)\n"
                f"  2. Confirm the interface name; currently "
                f"{self.config.interface_type}:{self.config.interface_name}\n"
                '     Query it with: python -c "import can;print(can.detect_available_configs())"\n'
                "  3. To check sequence logic only, add --dry-run"
            ) from None
        return self

    def __exit__(self, *exc) -> None:
        if self._hand is not None:
            self._hand.__exit__(*exc)

    def set_angles(self, angles) -> None:
        values = validate(angles)
        self._hand.angle.set_angles(values)

    def read_angles(self) -> list[float]:
        data = self._hand.angle.get_blocking(timeout_ms=500)
        return validate(data.angles.to_list())

    def read_force(self, fresh: bool = False) -> dict[str, int]:
        """Peak pressure cell per finger, as raw units (0-255).

        Uses the cached snapshot filled by the SDK's 30 Hz polling loop. With
        ``fresh=True`` it issues a blocking request instead, which bypasses a
        possibly stale cache.
        """
        snapshot = None
        if not fresh:
            snapshot = self._hand.force_sensor.get_snapshot()
        if snapshot is None:
            snapshot = self._hand.force_sensor.get_blocking(timeout_ms=800)
        return {finger: int(getattr(snapshot, finger).values.max()) for finger in FINGERS}

    def read_force_matrices(self) -> dict:
        """Raw 12x6 sensor matrices per finger, from a blocking request."""
        data = self._hand.force_sensor.get_blocking(timeout_ms=1000)
        return {finger: getattr(data, finger).values for finger in FINGERS}

    def read_torque(self) -> list[float]:
        """Joint torques in the same order as JOINT_NAMES."""
        data = self._hand.torque.get_blocking(timeout_ms=800)
        return validate(data.torques.to_list())


def open_hand(config: DeviceConfig, dry_run: bool = False):
    return DryRunHand(config) if dry_run else LinkerHand(config)


def wait_for_enter_or_ctrl_c() -> None:
    """Give the operator a moment before the hand starts moving."""
    print("Press Enter to start, Ctrl+C to abort...")
    try:
        sys.stdin.readline()
    except KeyboardInterrupt:
        raise SystemExit(0)
