"""CLI entry point: list / run / check / calibrate."""

from __future__ import annotations

import argparse
import time

from .config import load_device, load_gestures
from .device import DeviceConfig, open_hand, wait_for_enter_or_ctrl_c
from .joints import JOINT_NAMES, NUM_JOINTS
from .sequence import SequenceConfig, move_to, run_sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="l20_gestures",
        description="Gesture sequence runner for the LinkerHand L20 dexterous hand",
    )
    parser.add_argument("--dry-run", action="store_true", help="print commands, no hardware")
    parser.add_argument("--side", choices=["left", "right"], help="override the configured hand")
    parser.add_argument("--interface-type", help="override the CAN adapter type (pcan / socketcan)")
    parser.add_argument("--interface-name", help="override the CAN interface (PCAN_USBBUS1 / can0)")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="list gestures and the joint layout")

    run = sub.add_parser("run", help="execute gestures in order")
    run.add_argument("--sequence", required=True, help="comma-separated names, e.g. open,fist,ok")
    run.add_argument("--transition", type=float, help="seconds to blend between gestures")
    run.add_argument("--hold", type=float, help="seconds to hold each gesture")
    run.add_argument("--no-wait", action="store_true", help="skip the Enter confirmation")

    check = sub.add_parser("check", help="connect and read the current joint angles")
    check.add_argument("--timeout-ms", type=int, default=500)

    cali = sub.add_parser("calibrate", help="sweep one joint to confirm the value direction")
    cali.add_argument("--joint", required=True, help="joint name, e.g. index_root1")
    cali.add_argument("--duration", type=float, default=3.0, help="seconds for one sweep")
    cali.add_argument("--no-wait", action="store_true", help="skip the Enter confirmation")

    return parser


def cmd_list(gestures: dict) -> None:
    print("Joint order:")
    for index, name in enumerate(JOINT_NAMES):
        print(f"  {index:2d}  {name}")

    print("\nAvailable gestures:")
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
    print("Current angles:")
    for name, value in zip(JOINT_NAMES, angles):
        print(f"  {name:16s} {value:6.1f}")


def cmd_calibrate(args, device_cfg: DeviceConfig, seq_cfg: SequenceConfig) -> None:
    if args.joint not in JOINT_NAMES:
        raise SystemExit(f"unknown joint {args.joint}; available: {', '.join(JOINT_NAMES)}")
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
        print(f"[calibrate] {args.joint} -> 50 (neutral)")
        move_to(hand, start, high, args.duration, seq_cfg.fps)

    print("Note which end is extended and which is flexed, then edit config/gestures.yaml.")


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
