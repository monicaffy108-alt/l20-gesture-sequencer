# L20 Gesture Sequencer

Drive a [LinkerHand L20](https://www.linkerhand.com/) 16-DoF dexterous hand from code instead of dragging sliders in a GUI: smooth interpolation between gestures, YAML-based presets, and on-hardware calibration tools.

**Demo (22 s, real hardware)**: [media/l20_gesture_sequence_demo.mp4](media/l20_gesture_sequence_demo.mp4)

## Why this exists

A vendor GUI can make the hand move, but that only proves the hardware works. What counts as an engineering artifact is something that is repeatable from code, version-controlled, and demonstrable in a recorded run. This repository is the first layer of that: **a programmable gesture layer on top of 16 joint angles**.

Planned extensions on this foundation: simulation playback, hand teleoperation, and tactile data collection.

## Layout

```
l20-gesture-sequencer/
├── config/
│   ├── device.yaml       # hand side, CAN adapter type, sequence timing
│   └── gestures.yaml     # 7 gestures as 16-dimensional joint vectors
├── l20_gestures/
│   ├── joints.py         # joint order and range validation
│   ├── config.py         # config loading
│   ├── device.py         # hardware backend / dry-run backend
│   ├── force.py          # per-finger pressure metrics, contact detection
│   ├── sequence.py       # linear interpolation + timed updates
│   └── cli.py            # command-line entry point
└── requirements.txt
```

## Install

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Configuration

`config/device.yaml`:

| Setup | interface_type | interface_name |
|-------|----------------|----------------|
| Windows + PEAK PCAN | `pcan` | `PCAN_USBBUS1` |
| Ubuntu + SocketCAN | `socketcan` | `can0` |

On Ubuntu, bring the CAN interface up first:

```bash
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
```

Each gesture in `config/gestures.yaml` is 16 values in the range 0-100, ordered exactly as `JOINT_NAMES` in `l20_gestures/joints.py`.

## Usage

```bash
# 1. Validate the sequence logic without hardware
python -m l20_gestures --dry-run run --sequence relax,fist,open

# 2. Connectivity check (read-only, the hand does not move)
python -m l20_gestures check

# 3. Confirm the value direction of a single joint
python -m l20_gestures calibrate --joint index_root1
```

While `index_root1` sweeps from 0 to 100, note which end is extended and which is fully flexed, then correct `gestures.yaml` accordingly.

```bash
# 4. Run the full sequence while recording
python -m l20_gestures run --sequence relax,open,fist,open,point,ok,thumbs_up,open --transition 0.8 --hold 1.2
```

### Closed-loop grasp

```bash
# Read live pressure per finger, to pick a threshold
python -m l20_gestures force --duration 5

# Close until a finger touches, hold, then release
python -m l20_gestures grasp --target fist --threshold 30
```

The loop captures a pressure baseline in the open pose, then closes in fixed increments. As soon as any monitored finger rises above `threshold`, closing stops, the hand backs off one increment (so the object is held rather than crushed), holds for `grasp.hold`, and returns to the open pose.

Thresholds are raw sensor units (0-255), so they must be calibrated per hand with `force`. Restrict which fingers trigger the stop:

```bash
python -m l20_gestures grasp --fingers thumb,index --threshold 40
```

Command-line flags temporarily override the config:

```bash
python -m l20_gestures --side right --interface-name PCAN_USBBUS1 run --sequence open,fist
```

## Verification status

Every gesture was executed on a physical L20 (left hand, Windows + PCAN-USB) and inspected visually:

| Gesture | Status | Notes |
|---------|--------|-------|
| open / relax / point / thumbs_up | Passing | Pose matches the intended shape |
| fist | Passing | All five fingers close fully, no gap |
| ok | Passing | Thumb `abd=65 / yaw=70 / root1=40 / tip=25`, index `32/28` |
| pinch | Pending | Thumb reuses the tuned `ok` values; index and middle not tuned separately |

| Feature | Status |
|---------|--------|
| `grasp` closed loop (synthetic sensor) | Verified with `--dry-run`; stops at 40% closure |
| `grasp` closed loop (real sensor) | Not yet measured; threshold needs calibration with `force` |

Tuning history is recorded in the comments of `config/gestures.yaml`: thumb rotation `yaw` settled at 70 (30 was too far inward, 95 too far outward) and abduction `abd` at 65.

## Recording tips

1. **Code and hand in the same frame** — the running terminal command plus the actual hand motion, in one continuous take
2. **Label the gestures** — annotate each pose so the sequence reads clearly (open → fist → OK → thumbs up → open)
3. **Multiple angles** — one frontal take and one side take; the side view shows joint angles best
4. Keep the normal exit or `Ctrl+C` at the end, so it is visibly a real run rather than an edit

## Troubleshooting

**`A PCAN Channel has not been initialized yet` / channel in use**

A PCAN channel can only be claimed by one process at a time. The vendor GUI, PCAN-View, and browser control panels all hold it — close them all before running.

Check adapter availability:

```bash
python -c "import can;print(can.detect_available_configs())"
```

`channel_condition` `1` means available, `2` means occupied.

## Known limitations

- Value direction depends on firmware version; always confirm with `calibrate` on the target hand first
- Position control is open-loop; the `grasp` command adds contact feedback, but there is no closed-loop position tracking yet
- Interpolation is linear; if the motion looks jerky, lower `fps` or increase `transition`

## Roadmap

- [x] Gesture sequences + interpolation + CLI
- [x] Force-sensor closed loop: stop closing on contact
- [ ] URDF + MuJoCo synchronized playback (same commands, simulation and hardware side by side)
- [ ] RealSense + MediaPipe hand keypoints → joint angle mapping
