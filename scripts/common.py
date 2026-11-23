"""Shared configuration loading, OS-aware Google Drive discovery, and path helpers."""

from __future__ import annotations

from pathlib import Path
import platform
import string
from typing import Any
import yaml

KIT_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG_PATH = KIT_ROOT / "config.example.yaml"
LOCAL_CONFIG_CANDIDATES = (
    KIT_ROOT / "config.yaml",
    KIT_ROOT / "config.local.yaml",
)

MY_DRIVE_NAMES = ("My Drive", "我的云端硬盘", "我的雲端硬碟")
SUPPORTED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

STUDIO_SUBDIRS = (
    "notebooks",
    "models/checkpoints",
    "models/style_models",
    "models/clip_vision",
    "models/loras",
    "models/diffusion_models",
    "models/text_encoders",
    "models/vae",
    "workflows",
    "input_refs",
    "datasets",
    "outputs",
    "outputs_3d",
    "training_runs",
)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = val
    return merged


def load_config() -> dict[str, Any]:
    """Load config.example.yaml merged with optional config.yaml / config.local.yaml."""
    cfg: dict[str, Any] = {}
    if EXAMPLE_CONFIG_PATH.is_file():
        with EXAMPLE_CONFIG_PATH.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

    for candidate in LOCAL_CONFIG_CANDIDATES:
        if candidate.is_file():
            with candidate.open("r", encoding="utf-8") as f:
                user_cfg = yaml.safe_load(f) or {}
            cfg = _deep_merge(cfg, user_cfg)
    return cfg


def resolve_anchor_path(rel_or_abs: str) -> Path:
    """Resolve a style anchor path (absolute or relative to KIT_ROOT)."""
    p = Path(rel_or_abs).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (KIT_ROOT / p).resolve()


def _find_my_drive_in_parent(parent: Path) -> Path | None:
    for name in MY_DRIVE_NAMES:
        candidate = parent / name
        if candidate.is_dir():
            return candidate
    return None


def find_google_drive_my_drive(
    override: str | Path | None = None,
    config: dict[str, Any] | None = None,
) -> Path | None:
    """Locate Google Drive 'My Drive' root across macOS and Windows (EN/ZH locales)."""
    cfg = config if config is not None else load_config()
    raw_override = override if override is not None else cfg.get("drive_root_override")
    if raw_override:
        return Path(raw_override).expanduser().resolve()

    system = platform.system()
    if system == "Darwin":
        cloud_storage = Path.home() / "Library" / "CloudStorage"
        if cloud_storage.is_dir():
            for entry in sorted(cloud_storage.glob("GoogleDrive-*")):
                if entry.is_dir():
                    found = _find_my_drive_in_parent(entry)
                    if found is not None:
                        return found
        legacy_mount = Path("/Volumes/GoogleDrive")
        if legacy_mount.is_dir():
            found = _find_my_drive_in_parent(legacy_mount)
            if found is not None:
                return found

    elif system == "Windows":
        for letter in string.ascii_uppercase[3:]:  # D: .. Z:
            drive_root = Path(f"{letter}:/")
            if drive_root.is_dir():
                found = _find_my_drive_in_parent(drive_root)
                if found is not None:
                    return found

    return None


def get_studio_dir(
    drive_root: Path,
    config: dict[str, Any] | None = None,
) -> Path:
    """Return the GoogleOneAI_Studio directory under the resolved Drive root."""
    cfg = config if config is not None else load_config()
    folder_name = str(cfg.get("drive_folder_name") or "GoogleOneAI_Studio").strip()
    return drive_root / folder_name


def format_size(num_bytes: int) -> str:
    """Human-readable file size formatter."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{num_bytes} B"
