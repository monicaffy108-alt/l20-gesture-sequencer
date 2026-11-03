"""设备层：把 linkerbot SDK 包一层，方便切换真机 / dry-run。

SDK 采用延迟导入，没有装 linkerbot 或没有接硬件时，dry-run 依然能跑。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

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
    """不连硬件，把指令打印出来。用于验证序列逻辑。"""

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
        return list(self._last)


class LinkerHand:
    """真机后端，封装 linkerbot.L25。"""

    def __init__(self, config: DeviceConfig):
        self.config = config
        self._hand = None

    def __enter__(self) -> "LinkerHand":
        try:
            from linkerbot import L25
        except ImportError as exc:  # pragma: no cover - 取决于本机环境
            raise SystemExit(
                "没有找到 linkerbot SDK，请先执行：pip install linkerbot\n"
                "如果只想验证序列逻辑，可以加 --dry-run 参数。"
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
                f"连接失败：{exc}\n"
                "排查顺序：\n"
                "  1. 关掉所有占用 CAN 的程序（Windows 上位机、PCAN-View、灵巧手控制台网页）\n"
                f"  2. 确认接口名正确，当前为 {self.config.interface_type}:{self.config.interface_name}\n"
                "     可用 python -c \"import can;print(can.detect_available_configs())\" 查询\n"
                "  3. 只想验证序列逻辑，加 --dry-run"
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


def open_hand(config: DeviceConfig, dry_run: bool = False):
    return DryRunHand(config) if dry_run else LinkerHand(config)


def wait_for_enter_or_ctrl_c() -> None:
    """真机调试时给用户一点反应时间，避免上电瞬间猛动。"""
    print("按 Enter 开始执行，Ctrl+C 退出……")
    try:
        sys.stdin.readline()
    except KeyboardInterrupt:
        raise SystemExit(0)
