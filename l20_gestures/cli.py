"""命令行入口：list / run / check / calibrate。"""

from __future__ import annotations

import argparse
import time

from .config import load_device, load_gestures
from .device import DeviceConfig, open_hand, wait_for_enter_or_ctrl_c
from .joints import JOINT_NAMES, JOINT_NAMES_CN, NUM_JOINTS
from .sequence import SequenceConfig, move_to, run_sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="l20_gestures",
        description="L20 灵巧手手势序列执行器",
    )
    parser.add_argument("--dry-run", action="store_true", help="不连硬件，只打印指令")
    parser.add_argument("--side", choices=["left", "right"], help="覆盖配置里的左右手")
    parser.add_argument("--interface-type", help="覆盖 CAN 适配器类型，如 pcan / socketcan")
    parser.add_argument("--interface-name", help="覆盖 CAN 接口名，如 PCAN_USBBUS1 / can0")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出手势和关节表")

    run = sub.add_parser("run", help="按顺序执行手势")
    run.add_argument("--sequence", required=True, help="逗号分隔的手势名，如 open,fist,ok")
    run.add_argument("--transition", type=float, help="手势间过渡时长（秒）")
    run.add_argument("--hold", type=float, help="每个手势保持时长（秒）")
    run.add_argument("--no-wait", action="store_true", help="跳过按 Enter 确认")

    check = sub.add_parser("check", help="连接设备并读取当前角度")
    check.add_argument("--timeout-ms", type=int, default=500)

    cali = sub.add_parser("calibrate", help="单独扫动一个关节，确认数值方向")
    cali.add_argument("--joint", required=True, help="关节名，如 index_root1")
    cali.add_argument("--duration", type=float, default=3.0, help="单向扫动时长（秒）")
    cali.add_argument("--no-wait", action="store_true", help="跳过按 Enter 确认")

    return parser


def cmd_list(gestures: dict) -> None:
    print("关节顺序：")
    for index, (name, name_cn) in enumerate(zip(JOINT_NAMES, JOINT_NAMES_CN)):
        print(f"  {index:2d}  {name:16s} {name_cn}")

    print("\n可用手势：")
    for name, data in gestures.items():
        print(f"  {name:12s} {data.get('desc', '')}")


def make_configs(args):
    device_data, sequence_data = load_device()
    device = DeviceConfig.from_dict(device_data)
    if args.side:
        device.side = args.side
    if args.interface_type:
        device.interface_type = args.interface_type
    if args.interface_name:
        device.interface_name = args.interface_name

    seq = SequenceConfig.from_dict(sequence_data)
    if getattr(args, "transition", None) is not None:
        seq.transition = args.transition
    if getattr(args, "hold", None) is not None:
        seq.hold = args.hold
    return device, seq


def cmd_run(args, gestures: dict) -> None:
    device_cfg, seq_cfg = make_configs(args)
    names = [item.strip() for item in args.sequence.split(",") if item.strip()]

    if not args.no_wait and not args.dry_run:
        wait_for_enter_or_ctrl_c()

    with open_hand(device_cfg, dry_run=args.dry_run) as hand:
        run_sequence(hand, gestures, names, seq_cfg)


def cmd_check(args, device_cfg: DeviceConfig) -> None:
    with open_hand(device_cfg) as hand:
        angles = hand.read_angles()
    print("当前角度：")
    for name, value in zip(JOINT_NAMES, angles):
        print(f"  {name:16s} {value:6.1f}")


def cmd_calibrate(args, device_cfg: DeviceConfig, seq_cfg: SequenceConfig) -> None:
    if args.joint not in JOINT_NAMES:
        raise SystemExit(f"未知关节 {args.joint}，可用：{', '.join(JOINT_NAMES)}")
    index = JOINT_NAMES.index(args.joint)

    if not args.no_wait:
        wait_for_enter_or_ctrl_c()

    start = [50.0] * NUM_JOINTS
    low = list(start)
    low[index] = 0.0
    high = list(start)
    high[index] = 100.0

    with open_hand(device_cfg) as hand:
        print(f"[calibrate] {args.joint} -> 0")
        move_to(hand, low, start, args.duration, seq_cfg.fps)
        time.sleep(0.5)
        print(f"[calibrate] {args.joint} -> 100")
        move_to(hand, high, low, args.duration, seq_cfg.fps)
        time.sleep(0.5)
        print(f"[calibrate] 回到中立位 50")
        move_to(hand, start, high, args.duration, seq_cfg.fps)

    print("记住哪个方向是伸直、哪个是弯曲，直接改 config/gestures.yaml。")


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    gestures = load_gestures()

    if args.command == "list":
        cmd_list(gestures)
        return

    device_cfg, seq_cfg = make_configs(args)

    if args.command == "run":
        cmd_run(args, gestures)
    elif args.command == "check":
        cmd_check(args, device_cfg)
    elif args.command == "calibrate":
        cmd_calibrate(args, device_cfg, seq_cfg)
