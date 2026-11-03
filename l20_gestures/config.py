"""配置文件与路径加载。"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在：{path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_gestures(path: Path | None = None) -> dict:
    data = load_yaml(path or CONFIG_DIR / "gestures.yaml")
    gestures = data.get("gestures") or {}
    if not gestures:
        raise ValueError("gestures.yaml 里没有任何手势")
    return gestures


def load_device(path: Path | None = None) -> tuple[dict, dict]:
    data = load_yaml(path or CONFIG_DIR / "device.yaml")
    return data.get("device") or {}, data.get("sequence") or {}
