"""Mirror SDK joint values (0-100) onto the official L20 URDF in MuJoCo.

The URDF ships 21 revolute joints; four of them (the three DIP joints and the
thumb IP) are driven by <mimic> in ROS, which MuJoCo's URDF importer does not
evaluate. They are therefore commanded explicitly here.

Unit conversion:
    SDK sends 0-100 per joint, where 100 is the fully extended pose.
    URDF expects radians, where 0 is extended and the upper limit is flexed.
"""

from __future__ import annotations

import os
import time

import mujoco

from . import joints
from .config import ROOT

# The URDF has no lights, so MuJoCo renders it black. l20_left.xml is the same
# model exported with mj_saveLastXML plus two directional lights and a camera.
DEFAULT_URDF = "assets/linkerhand_l20/linkerhand_l20_left.urdf"
DEFAULT_MODEL = "assets/linkerhand_l20/l20_left.xml"

# field name -> (URDF joint name, kind)
#   "flex": 0 = extended, jnt_range[1] = fully flexed
#   "roll": symmetric about 0, jnt_range is [-r, +r], SDK 50 = centre
JOINT_MAP = {
    "thumb_abd": ("thumb_cmc_roll", "roll"),
    "thumb_yaw": ("thumb_cmc_yaw", "flex"),
    "thumb_root1": ("thumb_cmc_pitch", "flex"),
    "thumb_tip": ("thumb_mcp", "flex"),
    "index_abd": ("index_mcp_roll", "roll"),
    "index_root1": ("index_mcp_pitch", "flex"),
    "index_tip": ("index_pip", "flex"),
    "middle_abd": ("middle_mcp_roll", "roll"),
    "middle_root1": ("middle_mcp_pitch", "flex"),
    "middle_tip": ("middle_pip", "flex"),
    "ring_abd": ("ring_mcp_roll", "roll"),
    "ring_root1": ("ring_mcp_pitch", "flex"),
    "ring_tip": ("ring_pip", "flex"),
    "pinky_abd": ("pinky_mcp_roll", "roll"),
    "pinky_root1": ("pinky_mcp_pitch", "flex"),
    "pinky_tip": ("pinky_pip", "flex"),
}

# mimic relations taken from the URDF
MIMIC = {
    "index_dip": ("index_pip", 0.8917),
    "middle_dip": ("middle_pip", 0.8917),
    "ring_dip": ("ring_pip", 0.8917),
    "pinky_dip": ("pinky_pip", 0.8917),
    "thumb_ip": ("thumb_mcp", 1.1619),
}

ROLL_FLIP = {"index_mcp_roll", "middle_mcp_roll", "ring_mcp_roll", "pinky_mcp_roll"}

# One shared camera for the interactive viewer and the offscreen renderer, so a
# side-by-side video shows the same viewpoint in both panels.
CAMERA = {"lookat": (0.0, 0.0, 0.13), "distance": 0.45, "azimuth": 180.0,
          "elevation": -10.0}


def free_camera() -> "mujoco.MjvCamera":
    cam = mujoco.MjvCamera()
    cam.lookat[:] = CAMERA["lookat"]
    cam.distance = CAMERA["distance"]
    cam.azimuth = CAMERA["azimuth"]
    cam.elevation = CAMERA["elevation"]
    return cam


def resolve_model(path: str) -> str:
    """Make asset paths independent of the current working directory."""
    return path if os.path.isabs(path) else str(ROOT / path)


class HandModel:
    def __init__(self, model_path: str = DEFAULT_MODEL):
        self.model = mujoco.MjModel.from_xml_path(resolve_model(model_path))
        self.data = mujoco.MjData(self.model)
        self.command = [50.0] * joints.NUM_JOINTS
        self._qpos = {}
        for field, (joint_name, _) in JOINT_MAP.items():
            jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
            if jid < 0:
                raise ValueError(f"URDF has no joint named {joint_name}")
            self._qpos[field] = (jid, int(self.model.jnt_qposadr[jid]))
        self._mimic = {}
        for joint_name, (src_name, factor) in MIMIC.items():
            jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
            src_jid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, src_name)
            if jid >= 0 and src_jid >= 0:
                self._mimic[jid] = (
                    int(self.model.jnt_qposadr[src_jid]),
                    factor,
                )

    def apply(self, values) -> None:
        """Write one 16-element SDK pose into qpos and run forward kinematics."""
        values = joints.validate(values)
        self.command = values
        for field, value in zip(joints.JOINT_NAMES, values):
            joint_name, kind = JOINT_MAP[field]
            jid, adr = self._qpos[field]
            lo, hi = self.model.jnt_range[jid]
            if kind == "flex":
                angle = hi * (1.0 - value / 100.0)
            else:
                angle = hi * (value / 50.0 - 1.0)
                if joint_name in ROLL_FLIP:
                    angle = -angle
            self.data.qpos[adr] = angle

        for jid, (src_adr, factor) in self._mimic.items():
            self.data.qpos[int(self.model.jnt_qposadr[jid])] = (
                self.data.qpos[src_adr] * factor
            )

        mujoco.mj_forward(self.model, self.data)

    def camera(self, viewer) -> None:
        viewer.cam.lookat[:] = CAMERA["lookat"]
        viewer.cam.distance = CAMERA["distance"]
        viewer.cam.azimuth = CAMERA["azimuth"]
        viewer.cam.elevation = CAMERA["elevation"]


class SimHand:
    """Adapter with the same interface as the hardware backend.

    ``sequence.run_sequence`` only needs ``set_angles``, so wrapping the model
    here lets the simulation run the exact same playback code as the hand.
    """

    def __init__(self, model: HandModel, hand=None, viewer=None, measured: bool = False):
        self.model = model
        self.hand = hand
        self.viewer = viewer
        # True: display the encoder readings, so the sim shows where the hand
        # actually is (including tracking lag) instead of the commanded pose.
        self.measured = measured

    def set_angles(self, values) -> None:
        if self.hand is not None:
            self.hand.set_angles(values)
            if self.measured:
                values = self.hand.read_angles()
        self.model.apply(values)
        if self.viewer is not None:
            self.viewer.sync()

    def read_angles(self) -> list[float]:
        return list(self.model.command)


def mirror(model: HandModel, hand, viewer, fps: float = 30.0, seconds: float | None = None) -> None:
    """Copy the measured joint angles of the real hand into the simulation."""
    period = 1.0 / fps
    start = time.monotonic()
    while viewer.is_running():
        model.apply(hand.read_angles())
        viewer.sync()
        if seconds is not None and time.monotonic() - start > seconds:
            break
        time.sleep(period)


def render_sequence(model: HandModel, gestures: dict, names: list[str],
                    config, out_dir: str, width: int = 640, height: int = 480) -> int:
    """Render one PNG per interpolated frame, without opening a window."""
    from PIL import Image

    from .sequence import blend

    missing = [name for name in names if name not in gestures]
    if missing:
        raise ValueError(f"unknown gestures: {missing}; available: {sorted(gestures)}")
    os.makedirs(out_dir, exist_ok=True)

    renderer = mujoco.Renderer(model.model, height=height, width=width)
    camera = free_camera()
    frames = 0
    current = list(model.command)

    for index, name in enumerate(names):
        target = gestures[name]["angles"]
        steps = max(1, int(config.transition * config.fps))
        for step in range(1, steps + 1):
            model.apply(blend(current, target, step / steps))
            renderer.update_scene(model.data, camera=camera)
            Image.fromarray(renderer.render()).save(
                os.path.join(out_dir, f"{index:02d}_{name}_{step:03d}.png")
            )
            frames += 1
        current = list(target)
        for step in range(max(1, int(config.hold * config.fps))):
            renderer.update_scene(model.data, camera=camera)
            Image.fromarray(renderer.render()).save(
                os.path.join(out_dir, f"{index:02d}_{name}_hold_{step:03d}.png")
            )
            frames += 1

    renderer.close()
    return frames
