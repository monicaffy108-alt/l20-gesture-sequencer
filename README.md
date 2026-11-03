# L20 Gesture Sequencer

用代码（而不是手动拖滑块）驱动灵心巧手 L20 灵巧手执行手势序列，带平滑插值、参数化配置和真机校准工具。

**演示视频（22 秒，真机实测）**：[media/l20_gesture_sequence_demo.mp4](media/l20_gesture_sequence_demo.mp4)

> 换成 YouTube 链接后，把这一行替换成 `**演示视频**：[YouTube](链接)`。

## 为什么做这个

手动用上位机滑块能让手动作，但那只是验证硬件；能被代码复现、能进版本库、能录成对比视频的部分，才是可以写进项目里的东西。这个仓库是第一块：**把 16 个关节的控制封装成可编程的手势层**。

后续会在这个基础上接仿真同步、人手遥操作和触觉数据采集。

## 目录结构

```
l20-gesture-sequencer/
├── config/
│   ├── device.yaml       # 左右手、CAN 适配器类型、序列节奏
│   └── gestures.yaml     # 7 个手势的 16 维关节值
├── l20_gestures/
│   ├── joints.py         # 关节顺序、范围校验
│   ├── config.py         # 配置加载
│   ├── device.py         # 真机后端 / dry-run 后端
│   ├── sequence.py       # 线性插值 + 定时下发
│   └── cli.py            # 命令行入口
└── requirements.txt
```

## 安装

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## 配置

`config/device.yaml`：

| 场景 | interface_type | interface_name |
|------|----------------|----------------|
| Windows + PEAK PCAN | `pcan` | `PCAN_USBBUS1` |
| Ubuntu + SocketCAN | `socketcan` | `can0` |

Ubuntu 下先拉起 CAN 接口：

```bash
sudo ip link set can0 type can bitrate 1000000
sudo ip link set can0 up
```

`config/gestures.yaml` 里每个手势是 16 个 0-100 的数值，顺序与 `l20_gestures/joints.py` 中的 `JOINT_NAMES` 严格对应。

## 用法

```bash
# 1. 先不接硬件，确认序列逻辑
python -m l20_gestures --dry-run run --sequence relax,fist,open

# 2. 真机连通性检查（只读，不会让手动作）
python -m l20_gestures check

# 3. 校准方向：单独扫动一个关节
python -m l20_gestures calibrate --joint index_root1
```

看到 `index_root1` 的值从 0 扫到 100 时，确认哪一端是「伸直」、哪一端是「完全弯曲」，再据此改正 `gestures.yaml`。

```bash
# 4. 跑完整序列并录视频
python -m l20_gestures run --sequence relax,open,fist,open,point,ok,thumbs_up,open --transition 0.8 --hold 1.2
```

命令行参数可以临时覆盖配置：

```bash
python -m l20_gestures --side right --interface-name PCAN_USBBUS1 run --sequence open,fist
```

## 真机验证状态

在 L20（左手，Windows + PCAN-USB）上逐条跑过并确认手感：

| 手势 | 状态 | 备注 |
|------|------|------|
| open / relax / point / thumbs_up | 通过 | 形态符合预期 |
| fist | 通过 | 五指完全收拢，无缝隙 |
| ok | 通过 | 拇指 `abd=65 / yaw=70 / root1=40 / tip=25`，食指 `32/28` |
| pinch | 待验证 | 拇指沿用 ok 的实测值，食指中指未单独调 |

调参过程记录在 `config/gestures.yaml` 的注释里：拇指旋转 `yaw` 定在 70（30 太靠内、95 太靠外），侧摆 `abd` 定在 65。

## 录视频的建议

1. **代码和手同框**：终端里正在跑的命令 + 灵巧手的实际动作，一镜到底
2. **有标注**：每个手势配上文字，序列要完整（张开 → 握拳 → OK → 点赞 → 张开）
3. **多角度**：正面一遍、侧面一遍，侧面最能看出关节角度
4. 结尾保留 `Ctrl+C` 或正常退出的画面，证明是真实运行而非剪辑

## 常见问题

**`A PCAN Channel has not been initialized yet` / 通道被占用**

PCAN 通道同一时间只能被一个程序使用。Windows 上位机、PCAN-View、灵巧手控制台网页都会占着它，先全部关掉再跑。

查询适配器是否可用：

```bash
python -c "import can;print(can.detect_available_configs())"
```

`channel_condition` 为 `1` 表示可用，`2` 表示被占用。

## 已知限制

- 手势数值方向依赖固件版本，必须先在真机上跑 `calibrate` 确认
- 目前是开环位置控制，没有加入力传感器闭环（下一步）
- 插值用的是线性插值，实测如果出现抖动可以降低 `fps` 或增大 `transition`

## Roadmap

- [x] 手势序列 + 插值 + CLI
- [ ] 力传感器闭环：接触时停止收拢
- [ ] URDF + MuJoCo 同步回放（同一组指令，仿真与真机并排）
- [ ] RealSense + MediaPipe 人手关键点 → 关节角映射
