"""L20 / L25 灵巧手关节定义。

关节顺序与 linkerbot SDK 的 L25Angle 字段顺序一致，改动前请先对照官方文档：
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

JOINT_NAMES_CN = (
    "拇指侧摆",
    "拇指旋转",
    "拇指根部",
    "拇指指尖",
    "食指侧摆",
    "食指根部",
    "食指指尖",
    "中指侧摆",
    "中指根部",
    "中指指尖",
    "无名指侧摆",
    "无名指根部",
    "无名指指尖",
    "小指侧摆",
    "小指根部",
    "小指指尖",
)

NUM_JOINTS = len(JOINT_NAMES)

# 角度为无量纲值，范围 0-100，SDK 内部映射到电机实际角度。
ANGLE_MIN = 0.0
ANGLE_MAX = 100.0


def validate(values) -> list[float]:
    """把任意可迭代对象转成 16 维 float 列表，并做范围检查。"""
    values = [float(v) for v in values]
    if len(values) != NUM_JOINTS:
        raise ValueError(f"需要 {NUM_JOINTS} 个关节值，实际收到 {len(values)} 个")
    for name, value in zip(JOINT_NAMES, values):
        if not ANGLE_MIN <= value <= ANGLE_MAX:
            raise ValueError(f"关节 {name} 的值 {value} 超出范围 [{ANGLE_MIN}, {ANGLE_MAX}]")
    return values
