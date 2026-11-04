"""CLI entry point: list / run / check / calibrate."""

from __future__ import annotations

import argparse
import time

from .config import load_device, load_gestures, load_grasp
from .device import DeviceConfig, open_hand, wait_for_enter_or_ctrl_c
from .force import FINGERS, SOURCES, GraspConfig, close_until_contact, torque_metrics
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

    force = sub.add_parser("force", help="print live force sensor readings")
    force.add_argument("--duration", type=float, default=5.0, help="seconds to sample")
    force.add_argument("--interval", type=float, default=0.1, help="seconds between samples")
    force.add_argument("--raw", action="store_true",
                       help="print raw matrix stats and issue fresh requests")

    grasp = sub.add_parser("grasp", help="close until a finger registers contact")
    grasp.add_argument("--target", help="gesture to close towards (default from config)")
    grasp.add_argument("--source", choices=SOURCES,
                       help="contact signal: force, torque or angle_error")
    grasp.add_argument("--steps", type=int, help="increments from open to target")
    grasp.add_argument("--interval", type=float, help="seconds between increments")
    grasp.add_argument("--threshold", type=float, help="pressure delta counted as contact")
    grasp.add_argument("--torque-threshold", type=float, help="torque delta counted as contact")
    grasp.add_argument("--tolerance", type=float, help="tracking lag in degrees counted as contact")
    grasp.add_argument("--fingers", help="comma-separated subset, e.g. thumb,index")
    grasp.add_argument("--hold", type=float, help="seconds to hold the grip")
    grasp.add_argument("--no-wait", action="store_true", help="skip the Enter confirmation")

    torque = sub.add_parser("torque", help="print live joint torque readings")
    torque.add_argument("--duration", type=float, default=5.0, help="seconds to sample")
    torque.add_argument("--interval", type=float, default=0.1, help="seconds between samples")

    sim = sub.add_parser("sim", help="mirror the hand or replay gestures in MuJoCo")
    sim.add_argument("--sequence", help="comma-separated gestures; omit to mirror the real hand")
    sim.add_argument("--drive", action="store_true",
                     help="also command the real hand, so both sides move together")
    sim.add_argument("--measured", action="store_true",
                     help="with --drive: render the measured (encoder) angles, not the commanded ones")
    sim.add_argument("--render-dir", help="write PNG frames instead of opening a viewer")
    sim.add_argument("--model", help="model path (default: assets/linkerhand_l20/l20_left.xml)")
    sim.add_argument("--seconds", type=float, help="mirror mode: stop after N seconds")
    sim.add_argument("--fps", type=float, default=30.0, help="mirror mode refresh rate")
    sim.add_argument("--width", type=int, default=640, help="offscreen frame width")
    sim.add_argument("--height", type=int, default=480, help="offscreen frame height")
    sim.add_argument("--no-wait", action="store_true", help="skip the Enter confirmation")

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


def cmd_force(args, device_cfg: DeviceConfig, dry_run: bool) -> None:
    if args.raw:
        print("              " + " ".join(f"{finger:>15s}" for finger in FINGERS))
        print("              " + " ".join(f"{'max/sum':>15s}" for _ in FINGERS))
    else:
        print("          " + " ".join(f"{finger:>7s}" for finger in FINGERS))

    with open_hand(device_cfg, dry_run=dry_run) as hand:
        end = time.monotonic() + args.duration
        while time.monotonic() < end:
            if args.raw:
                matrices = hand.read_force_matrices()
                cells = []
                for finger in FINGERS:
                    matrix = matrices[finger]
                    if matrix is None:
                        cells.append(f"{'n/a':>15s}")
                    else:
                        cells.append(f"{int(matrix.max()):>7d}/{int(matrix.sum()):<7d}")
                print("  " + " ".join(cells))
            else:
                metrics = hand.read_force()
                print("  " + " ".join(f"{metrics[finger]:7d}" for finger in FINGERS))
            time.sleep(args.interval)


def cmd_torque(args, device_cfg: DeviceConfig, dry_run: bool) -> None:
    print("          " + " ".join(f"{finger:>7s}" for finger in FINGERS))
    with open_hand(device_cfg, dry_run=dry_run) as hand:
        end = time.monotonic() + args.duration
        while time.monotonic() < end:
            try:
                metrics = torque_metrics(hand.read_torque())
            except TimeoutError:
                print("  (no torque data - device did not respond)")
            else:
                print("  " + " ".join(f"{metrics[finger]:7.1f}" for finger in FINGERS))
            time.sleep(args.interval)


def cmd_grasp(args, gestures: dict, device_cfg: DeviceConfig,
              seq_cfg: SequenceConfig, dry_run: bool) -> None:
    config = GraspConfig.from_dict(load_grasp())
    if args.target:
        config.target = args.target
    if args.source:
        config.source = args.source
    if args.steps is not None:
        config.steps = args.steps
    if args.interval is not None:
        config.interval = args.interval
    if args.threshold is not None:
        config.threshold = args.threshold
    if args.torque_threshold is not None:
        config.torque_threshold = args.torque_threshold
    if args.tolerance is not None:
        config.tolerance = args.tolerance
    if args.hold is not None:
        config.hold = args.hold
    if args.fingers:
        config.fingers = tuple(item.strip() for item in args.fingers.split(",") if item.strip())

    if config.target not in gestures:
        raise SystemExit(f"unknown target gesture {config.target}; available: {sorted(gestures)}")
    unknown = [finger for finger in config.fingers if finger not in FINGERS]
    if unknown:
        raise SystemExit(f"unknown fingers {unknown}; available: {', '.join(FINGERS)}")

    if not args.no_wait and not dry_run:
        wait_for_enter_or_ctrl_c()

    with open_hand(device_cfg, dry_run=dry_run) as hand:
        start = gestures["open"]["angles"]
        current = hand.read_angles()
        if any(value != value for value in current):  # dry-run before any command
            current = list(start)
        move_to(hand, start, current, seq_cfg.transition, seq_cfg.fps)
        time.sleep(0.3)

        result = close_until_contact(hand, start, gestures[config.target]["angles"], config)

        if result["finger"]:
            print(
                f"contact ({result['source']}): {result['finger']} "
                f"{result['value']:.1f} at {result['ratio'] * 100:.0f}% closure"
            )
        else:
            print(f"no contact within {config.steps} steps ({result['ratio'] * 100:.0f}% closure)")

        time.sleep(config.hold)
        print("releasing")
        move_to(hand, start, result["angles"], seq_cfg.transition, seq_cfg.fps)


def cmd_sim(args, gestures: dict, device_cfg: DeviceConfig, seq_cfg: SequenceConfig,
            dry_run: bool) -> None:
    from contextlib import ExitStack

    try:
        import mujoco
        import mujoco.viewer  # not imported by `import mujoco` alone
    except ImportError:
        raise SystemExit("mujoco is not installed. Install it with: pip install mujoco")

    from .sim import DEFAULT_MODEL, HandModel, SimHand, mirror, render_sequence

    model = HandModel(args.model or DEFAULT_MODEL)
    names = [item.strip() for item in args.sequence.split(",") if item.strip()] if args.sequence else []

    if args.render_dir:
        if not names:
            raise SystemExit("--render-dir needs --sequence; nothing to animate otherwise")
        frames = render_sequence(model, gestures, names, seq_cfg, args.render_dir,
                                 args.width, args.height)
        print(f"rendered {frames} frames to {args.render_dir}")
        return

    if not names and dry_run:
        raise SystemExit("mirror mode reads the real hand; use --sequence with --dry-run")

    if names and not args.no_wait and not dry_run:
        wait_for_enter_or_ctrl_c()

    with mujoco.viewer.launch_passive(model.model, model.data) as viewer:
        model.camera(viewer)
        if names:
            with ExitStack() as stack:
                hand = stack.enter_context(open_hand(device_cfg)) if args.drive and not dry_run else None
                run_sequence(SimHand(model, hand, viewer, measured=args.measured),
                             gestures, names, seq_cfg)
        else:
            with open_hand(device_cfg) as hand:
                print("Mirroring. Move the hand by hand; close the window or Ctrl+C to stop.")
                mirror(model, hand, viewer, args.fps, args.seconds)


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
    elif args.command == "force":
        cmd_force(args, device_cfg, args.dry_run)
    elif args.command == "torque":
        cmd_torque(args, device_cfg, args.dry_run)
    elif args.command == "grasp":
        cmd_grasp(args, gestures, device_cfg, seq_cfg, args.dry_run)
    elif args.command == "sim":
        cmd_sim(args, gestures, device_cfg, seq_cfg, args.dry_run)
