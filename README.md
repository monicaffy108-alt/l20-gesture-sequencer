# L20 Gesture Sequencer

<p align="center">
  <img src="https://img.shields.io/badge/hardware-LinkerHand_L20-orange" alt="LinkerHand L20">
  <img src="https://img.shields.io/badge/simulation-MuJoCo-red" alt="MuJoCo">
  <img src="https://img.shields.io/badge/vision-MediaPipe-green" alt="MediaPipe">
  <img src="https://img.shields.io/badge/sensor-RealSense_D405-teal" alt="RealSense D405">
  <img src="https://img.shields.io/badge/platform-Windows_%7C_Linux-lightgrey" alt="Windows | Linux">
  <img src="https://img.shields.io/badge/Python-blue?logo=python&logoColor=white" alt="Python">
</p>

Drive a [LinkerHand L20](https://www.linkerhand.com/) 16-DoF dexterous hand from code instead of dragging sliders in a GUI: smooth interpolation between gestures, YAML-based presets, and on-hardware calibration tools.

**Gesture sequence (22 s, real hardware)**: [media/l20_gesture_sequence_demo.mp4](media/l20_gesture_sequence_demo.mp4)  
**Closed-loop grasp (YouTube Shorts)**: https://youtube.com/shorts/fceqbrzrN8s — fingertip-pressure-based contact detection, stops at 55% closure; local copy also at `media/`

## Why this exists

A vendor GUI can make the hand move, but that only proves the hardware works. What counts as an engineering artifact is something that is repeatable from code, version-controlled, and demonstrable in a recorded run. This repository is the first layer of that: **a programmable gesture layer on top of 16 joint angles**.

Planned extensions on this foundation: simulation playback, hand teleoperation, and tactile data collection.

## Layout

```
l20-gesture-sequencer/
├── assets/
│   ├── linkerhand_l20/   # official URDF + meshes, plus a lit MJCF export
│   └── models/           # MediaPipe hand landmark model
├── config/
│   ├── device.yaml       # hand side, CAN adapter type, sequence timing
│   └── gestures.yaml     # 7 gestures as 16-dimensional joint vectors
├── l20_gestures/
│   ├── joints.py         # joint order and range validation
│   ├── config.py         # config loading
│   ├── device.py         # hardware backend / dry-run backend
│   ├── force.py          # contact signals: pressure, torque, tracking error
│   ├── sequence.py       # linear interpolation + timed updates
│   ├── sim.py            # SDK angles -> URDF joints, MuJoCo viewer and renderer
│   ├── teleop.py         # camera hand tracking -> 16 joint values
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
# Inspect the available contact signals
python -m l20_gestures force --raw --duration 5
python -m l20_gestures torque --duration 10

# Close until contact, hold, then release (default: force)
python -m l20_gestures grasp
```

The loop closes in fixed increments from the open pose and stops as soon as contact is detected, then backs off one increment (so the object is held rather than crushed), holds for `grasp.hold`, and returns to the open pose.

Three contact signals are supported:

| `--source` | Signal | Measured on this unit |
|-----------|--------|----------------------|
| `force` | fingertip pressure (raw 0-255 matrix, peak cell per finger) | **Default and verified.** Empty hand reads 0; a firm fingertip press reads 80-127 (`grasp --threshold 30`) |
| `angle_error` | lag between commanded and measured angle (degrees) | Dry-run verified; hardware run pending |
| `torque` | joint torque rise (SDK's 0-100 units) | **Not usable.** Reads a constant 3.5 (thumb) / 0 (others) whether loaded or not — the reported value does not track load |

Hardware result with `force`: contact detected at 55% closure (`contact (force): thumb 82.0 at 55% closure`), followed by the one-increment back-off.

An implementation pitfall worth knowing: reading the force sensor with one-off blocking requests (`get_blocking`) returns all-zero matrices while the SDK's 30 Hz polling loop is active — the polling sink consumes the replies. Reading from the polling snapshot instead returns correct data. All sensor reads in this repo therefore go through snapshots, with blocking requests only as a fallback.

Command-line flags temporarily override the config:

```bash
python -m l20_gestures --side right --interface-name PCAN_USBBUS1 run --sequence open,fist
```

## Simulation (MuJoCo)

The official URDF is loaded in MuJoCo and driven by the same 16 joint values the hand receives, so simulation and hardware can be recorded side by side.

```bash
# Replay gestures in the simulator, no hardware
python -m l20_gestures --dry-run sim --sequence open,fist,ok --no-wait

# Command the real hand and the simulator at the same time (side-by-side capture)
python -m l20_gestures sim --sequence open,fist,ok --drive

# Same, but the simulator renders the measured encoder angles instead of the
# commanded ones — the sim visibly tracks where the hand actually is
python -m l20_gestures sim --sequence open,fist,ok --drive --measured

# Render frames to PNG instead of opening a window
python -m l20_gestures sim --sequence open,fist,ok --render-dir sim_frames
```

Note on mirror mode (`sim` with no `--sequence`): it holds the CAN channel exclusively — PCAN allows only one process per channel — so it cannot run alongside a second terminal commanding the hand, and the fingers cannot be backdriven by hand while powered. Kept for dual-adapter setups; on a single adapter, use `--drive --measured` instead.

How the mapping works:

- The URDF has 21 revolute joints; the SDK exposes 16. The three DIP joints and the thumb IP are `<mimic>` joints in ROS, which the MuJoCo URDF importer does not evaluate, so `sim.py` writes them explicitly (factors taken from the URDF).
- SDK values are 0-100 with 100 = fully extended; URDF expects radians with 0 = extended, so flexion is `range_max * (1 - value / 100)`.
- The four abduction joints are symmetric about 0, so SDK 50 is the centre; their sign is flipped to match the URDF axis direction.
- The URDF contains no lights, so an unlit render is black. `assets/linkerhand_l20/l20_left.xml` is the same model exported with `mj_saveLastXML` plus two directional lights. The camera is shared by the viewer and the renderer (see `CAMERA` in `sim.py`).

Sign conventions were derived from the URDF axes and checked by rendering the known gestures; if a joint moves the wrong way on your hand, that is the table to look at.

## Hand teleoperation

MediaPipe tracks a human hand in the camera image, the landmark geometry is converted to the same 16 joint values the rest of this package uses, and the hand follows in real time. No depth data is needed — the 2D landmarks are enough to recover finger flexion and lateral spread.

```bash
# RealSense (default). Preview window plus a live readout per joint
python -m l20_gestures teleop

# Plain webcam
python -m l20_gestures teleop --camera webcam --device-id 0

# Camera only, no hand movement — useful for checking the mapping first
python -m l20_gestures --dry-run teleop --no-preview --duration 5
```

Download the model once (it is not committed, ~7.5 MB):

```bash
mkdir -p assets/models
curl -L -o assets/models/hand_landmarker.task \
  https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task
```

How the 21 landmarks become 16 joints:

| Signal | Measurement |
|--------|-------------|
| `*_root1` | smaller of the MCP angle (wrist-MCP-PIP) and the PIP angle (MCP-PIP-DIP). 2D projection foreshortens MCP rotation, so taking the minimum keeps a closed fist closed |
| `*_tip` | PIP angle (MCP-PIP-DIP). The DIP joint is the URDF mimic and is not measured separately |
| `*_abd` (four fingers) | signed lateral angle of each finger away from the middle finger, faded towards neutral as the finger curls (a closed fist collapses the projected knuckles, so the raw reading is meaningless there) |
| `thumb_abd` | opening angle between the thumb chain and the index chain |
| `thumb_yaw / root1 / tip` | angles at the CMC, MCP and IP joints of the thumb |

The mapping is deliberately in the 0-100 SDK space (100 = extended, 0 = flexed), so it composes with `gestures.yaml`, `grasp` and `sim`.

Two filters keep the motion usable:

- **EMA smoothing** (`--alpha`, default 0.5) removes landmark jitter
- **Per-update clamp** (`--max-step`, default 6) limits how far a joint may move in one cycle, so a tracking glitch cannot slam a finger

If tracking is lost the last pose is held rather than snapping to a default. `--no-mirror` disables the horizontal flip; mirroring is on by default because un-mirrored camera motion feels inverted to the operator.

Note: `--mirror` flips handedness, so all lateral angles invert with it. Check the spread direction on the hardware once; if a finger abducts the wrong way, remove `--mirror` or negate `ABD_GAIN` in `teleop.py`.

## Third-party assets

`assets/linkerhand_l20/` is the L20 left-hand description from [linker-bot/linkerhand-urdf](https://github.com/linker-bot/linkerhand-urdf), licensed under Apache 2.0 (see `LICENSE-linkerhand-urdf` in that folder). The URDF is vendored unmodified; `l20_left.xml` is a generated export of it.

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
| `grasp` with `force` | **Verified on hardware** — contact at 55% closure, threshold 30 calibrated (empty: 0, press: 80-127) |
| `grasp` with `angle_error` | Dry-run verified; hardware run pending |
| `grasp` with `torque` | Not usable on this unit: torque is constant regardless of load |
| `teleop` (RealSense D405 + MediaPipe) | **Verified on hardware** — 30 Hz tracking, hand follows the operator in real time |

Measured tracking characteristics of the teleop mapping:

| Signal | Result |
|--------|--------|
| Finger flexion (`root1`, `tip`) | Smooth and stable; a closed fist drives all four fingers to 0 |
| Thumb flexion | Partial — the thumb curls towards the camera, so most of its motion lies along the optical axis and is lost in a monocular projection |
| Lateral spread (`abd`) | Usable when the finger is extended; faded to neutral as it curls, because a closed fist collapses the projected knuckles |

## Measured results

All numbers below were produced by `python -m l20_gestures bench` on the same physical unit
(left hand, Windows + PCAN-USB). Values are SDK units on the 0-100 scale unless noted.

### Position tracking

Each gesture was commanded, allowed to settle for 0.8 s, and then compared against the
encoder reading.

| Gesture | Mean error | Max error | Joint with the max |
|---------|-----------|-----------|--------------------|
| open | 6.6 | 100.0 | thumb_root1 |
| fist | 4.5 | 47.8 | thumb_tip |
| relax | 4.4 | 65.0 | thumb_root1 |
| point | 6.7 | 100.0 | thumb_root1 |
| thumbs_up | 10.2 | 100.0 | thumb_root1 |
| ok | 2.9 | 40.0 | thumb_root1 |
| pinch | 2.8 | 40.0 | thumb_root1 |

Mean absolute error across all joints and gestures: **5.4**. RMS: 19.1, which is inflated
almost entirely by `thumb_root1`: in the three poses that command the thumb fully extended,
the encoder reports 0 instead of 100. The four finger chains track within a few units, and
the two pinch poses (`ok`, `pinch`) track within 3 units on average.

### Step response

`index_root1`, commanded as a step from 0 to 100, sampled at 60 Hz, three runs of three
repeats:

| Metric | Value |
|--------|-------|
| Rise to 63% (`t63`) | 448 ms (all nine repeats between 447 and 465 ms) |
| Rise to 90% (`t90`) | 606 ms (sd 9-19 ms across runs) |
| Settled value | 91.4 (the joint saturates about 9 units below the command) |

### Closed-loop grasp

Twenty trials per object, closing towards `fist` from `open`, stopping on fingertip
pressure above 30. The object was placed by hand in the palm before each trial, so its
position varied between trials.

| Object | Contact detected | Closure at contact | Load after back-off |
|--------|------------------|--------------------|---------------------|
| Bag of chips (soft, large) | 19/20 (95%) | 70.3% (sd 13.6) | 6/20 |
| Water bottle (rigid) | 20/20 | 39.2% (sd 8.3) | 10/20 |

Reading these numbers: the loop reliably detects contact and stops — 95% and 100% of
trials — and the closure depth is repeatable within about 10 percentage points. The
"load after back-off" column is not a grasp success rate: the loop backs off one
increment by design so it never crushes, and whether a loosely-held object stays up
depends on friction and on where it happened to be placed. A soft bag also registers
contact early (70% closure) merely by touching the palm, before the fingers can wrap it.

## Benchmarks

```bash
# Steady-state tracking error across all gestures
python -m l20_gestures bench --test tracking

# Step response of a single joint
python -m l20_gestures bench --test step --joint index_root1

# Repeat the closed-loop grasp and count contacts
python -m l20_gestures bench --test grasp --trials 20
```


Tuning history is recorded in the comments of `config/gestures.yaml`: thumb rotation `yaw` settled at 70 (30 was too far inward, 95 too far outward) and abduction `abd` at 65.

## Recording tips

1. **Code and hand in the same frame** — the running terminal command plus the actual hand motion, in one continuous take
2. **Label the gestures** — annotate each pose so the sequence reads clearly (open → fist → OK → thumbs up → open)
3. **Multiple angles** — one frontal take and one side take; the side view shows joint angles best
4. Keep the normal exit or `Ctrl+C` at the end, so it is visibly a real run rather than an edit

## Video caption (YouTube)

Suggested on-screen text card and spoken subtitles, American English:

```
Project: L20 Gesture Sequencer with Tactile-Closed-Loop Grasping
Hardware: LinkerHand L20 Dexterous Hand (16 active DoF)
Contact signal: Fingertip pressure sensor, threshold = 30 (0-255 scale)
Result: Grasps detected at 55% closure, object held without crushing
```

| Spoken subtitle | Notes |
|----------------|-------|
| "No-load baseline shows near-zero pressure across all fingers" | Free hand in air |
| "Under firm fingertip contact, pressure rises to 80-127 on the raw 0-255 scale" | Calibration shot |
| "A 20-step closure stops as soon as any finger crosses threshold 30" | Grasp loop |
| "Contact detected — thumb 82 at 55% closure" | Terminal echo |
| "Back off one step, hold, then release" | Shows the grip, not a crush |

## Interview talking points

If asked about implementation details, the polling-vs-snapshot pitfall is a good story to tell:

> "One subtle issue I found when integrating the pressure sensor was that the SDK's 30 Hz polling loop and one-off blocking requests contend on the CAN bus. When I called `get_blocking()` to read the 12×6 fingertip matrices, the poller had already consumed every reply, so I got all-zero matrices even under firm contact. The fix was simple — read from the polling snapshot instead. It's a small pitfall, but it illustrates how hardware integration often hinges on understanding the middleware's threading model, not just the sensor API."

Key terms you should be able to explain: polling, snapshot, CAN bus arbitration, tactile pressure matrix, force threshold calibration.

## Troubleshooting

**`A PCAN Channel has not been initialized yet` / channel in use**

A PCAN channel can only be claimed by one process at a time. The vendor GUI, PCAN-View, and browser control panels all hold it — close them all before running.

Check adapter availability:

```bash
python -c "import can;print(can.detect_available_configs())"
```

`channel_condition` `1` means available, `2` means occupied.

**RealSense enumerates but `wait_for_frames` times out**

On a D405 this happened after the device came up on a stale USB mode: `query_devices` listed the camera, but only the stereo sensor was exposed and the color stream never delivered a frame. A hardware reset fixes it without unplugging:

```python
import pyrealsense2 as rs, time
dev = list(rs.context().query_devices())[0]
dev.hardware_reset(); time.sleep(6)
```

After the reset the device reported USB 3.2 and `enable_stream(rs.stream.color, ...)` worked. If it still fails, move the cable to a USB 3 port — on USB 2 the color sensor may not enumerate at all.

## Known limitations

- `thumb_root1` does not respond through this SDK on the test unit: the encoder reports a constant 0 and no position command moves the joint, while the vendor console drives it without issue. The byte position is not the cause — both this SDK and the vendor's ROS 2 SDK put `thumb_root1` in the third data byte of frame `0x41` (after roll and yaw) and read it back from the same slot. The remaining difference is that the ROS 2 SDK also exposes a parallel command set (`0x03 ROOT1_POS`, one value per finger), which the console most likely uses. The pose library does not rely on this axis — `thumb_yaw`, `thumb_abd` and `thumb_tip` produce the thumb shapes
- Value direction depends on firmware version; always confirm with `calibrate` on the target hand first
- Position control is open-loop; the `grasp` command adds contact feedback, but there is no closed-loop position tracking yet
- Interpolation is linear; if the motion looks jerky, lower `fps` or increase `transition`

## Roadmap

- [x] Gesture sequences + interpolation + CLI
- [x] Force-sensor closed loop: stop closing on contact
- [x] URDF + MuJoCo synchronized playback (same commands, simulation and hardware side by side)
- [x] RealSense + MediaPipe hand keypoints → joint angle mapping (`teleop`)
- [ ] Record teleop episodes in LeRobot dataset format and train a policy (ACT / π₀)
