"""Config file and path loading."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_gestures(path: Path | None = None) -> dict:
    data = load_yaml(path or CONFIG_DIR / "gestures.yaml")
    gestures = data.get("gestures") or {}
    if not gestures:
        raise ValueError("gestures.yaml defines no gestures")
    return gestures


def load_device(path: Path | None = None) -> tuple[dict, dict]:
    data = load_yaml(path or CONFIG_DIR / "device.yaml")
    return data.get("device") or {}, data.get("sequence") or {}


def load_grasp(path: Path | None = None) -> dict:
    data = load_yaml(path or CONFIG_DIR / "device.yaml")
    return data.get("grasp") or {}
