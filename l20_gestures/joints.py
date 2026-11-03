"""Joint layout of the LinkerHand L20 / L25 dexterous hand.

The order matches the field order of ``L25Angle`` in the linkerbot SDK.
Check the official reference before changing anything:
https://docs.linkerhub.work/sdk/zh-cn/reference/l25/angle.html
"""

JOINT_NAMES = (
    "thumb_abd",
    "thumb_yaw",
    "thumb_root1",
    "thumb_tip",
    "index_abd",
    "index_root1",
    "index_tip",
    "middle_abd",
    "middle_root1",
    "middle_tip",
    "ring_abd",
    "ring_root1",
    "ring_tip",
    "pinky_abd",
    "pinky_root1",
    "pinky_tip",
)

NUM_JOINTS = len(JOINT_NAMES)

# Values are dimensionless, 0-100. The SDK maps them to motor angles internally.
ANGLE_MIN = 0.0
ANGLE_MAX = 100.0


def validate(values) -> list[float]:
    """Coerce an iterable into a 16-element float list and check the range."""
    values = [float(v) for v in values]
    if len(values) != NUM_JOINTS:
        raise ValueError(f"expected {NUM_JOINTS} joint values, got {len(values)}")
    for name, value in zip(JOINT_NAMES, values):
        if not ANGLE_MIN <= value <= ANGLE_MAX:
            raise ValueError(
                f"joint {name} value {value} is outside [{ANGLE_MIN}, {ANGLE_MAX}]"
            )
    return values
