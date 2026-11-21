#!/usr/bin/env python3
"""Inspect local Python dependencies, Google Drive mount status, studio models, and Colab URLs."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (  # noqa: E402
    KIT_ROOT,
    SUPPORTED_IMAGE_EXTS,
    find_google_drive_my_drive,
    format_size,
    get_studio_dir,
    load_config,
    resolve_anchor_path,
)
from get_colab_urls import collect_colab_urls  # noqa: E402


def _check_dependencies() -> None:
    print(f"[Python] {sys.version.split()[0]} ({sys.executable})")
    for pkg in ("PIL", "yaml"):
        try:
            mod = __import__(pkg)
            ver = getattr(mod, "__version__", "ok")
            print(f"[OK] 依赖 {pkg}: {ver}")
        except ImportError:
            print(f"[MISSING] 依赖 {pkg} 未安装，请运行 .venv/bin/pip install -r requirements.txt")


def _check_local_kit(cfg: dict) -> None:
    print("\n=== 本地工程与参考图 ===")
    print(f"  [Kit Root] {KIT_ROOT}")
    nbs = sorted((KIT_ROOT / "notebooks").glob("*.ipynb"))
    wfs = sorted((KIT_ROOT / "workflows").glob("*.json"))
    print(f"  [OK] Colab Notebooks ({len(nbs)}): {[p.name for p in nbs]}")
    print(f"  [OK] ComfyUI Workflows ({len(wfs)}): {[p.name for p in wfs]}")

    anchors = cfg.get("style_anchors") or {}
    refs_dir = KIT_ROOT / "workspace" / "style_refs"
    local_refs = [p for p in sorted(refs_dir.iterdir())] if refs_dir.is_dir() else []
    local_refs = [p for p in local_refs if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTS]

    if not anchors and not local_refs:
        print("  [INFO] 暂未配置风格参考图（可把参考图放入 workspace/style_refs/ 或写入 config.local.yaml）")
        return

    for target_name, raw_path in anchors.items():
        src = resolve_anchor_path(raw_path)
        if src.is_file():
            print(f"  [OK] 参考图 {target_name} <- {src} ({format_size(src.stat().st_size)})")
        else:
            print(f"  [MISSING] 参考图 {target_name} <- {src}")

    for p in local_refs:
        print(f"  [OK] 本地参考图 workspace/style_refs/{p.name} ({format_size(p.stat().st_size)})")


def _inspect_studio(studio_dir: Path) -> None:
    print(f"\n=== Google Drive 云端工作区 ({studio_dir}) ===")
    if not studio_dir.exists():
        print(f"  [未初始化] 尚未创建 {studio_dir.name}。请运行:")
        print("    .venv/bin/python scripts/sync_to_drive.py")
        return

    buckets = [
        ("notebooks", "*.ipynb"),
        ("workflows", "*.json"),
        ("input_refs", "*"),
        ("models/checkpoints", "*.safetensors"),
        ("models/style_models", "*.safetensors"),
        ("models/clip_vision", "*.safetensors"),
        ("models/loras", "*.safetensors"),
        ("outputs", "*"),
    ]
    for sub, pattern in buckets:
        folder = studio_dir / sub
        if not folder.is_dir():
            print(f"  [MISSING DIR] {sub}/")
            continue
        files = [p for p in sorted(folder.glob(pattern)) if p.is_file() and not p.name.startswith(".")]
        total_sz = sum(p.stat().st_size for p in files)
        names = ", ".join(p.name for p in files[:4])
        if len(files) > 4:
            names += f", ... (+{len(files) - 4})"
        detail = f": {names}" if files else ""
        print(f"  [DIR] {sub}/ -> {len(files)} 个文件 ({format_size(total_sz)}){detail}")

    datasets_dir = studio_dir / "datasets"
    if datasets_dir.is_dir():
        for ds in sorted(p for p in datasets_dir.iterdir() if p.is_dir()):
            imgs = [p for p in ds.iterdir() if p.suffix.lower() in {".png", ".jpg", ".jpeg"}]
            txts = [p for p in ds.iterdir() if p.suffix.lower() == ".txt"]
            print(f"  [DATASET] datasets/{ds.name}/ -> {len(imgs)} 图 / {len(txts)} 标注")

    urls = collect_colab_urls(studio_dir)
    ready_urls = [u for u in urls if u["colab_url"]]
    if ready_urls:
        print("\n=== Colab 直达链接 ===")
        for u in ready_urls:
            print(f"  {u['name']}: {u['colab_url']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 Google One AI Kit 本地与云端环境状态。")
    parser.add_argument("--drive-root", help="可选：手动指定 Google Drive 'My Drive' 目录路径")
    args = parser.parse_args()

    cfg = load_config()
    _check_dependencies()
    _check_local_kit(cfg)

    drive_root = find_google_drive_my_drive(args.drive_root, cfg)
    if drive_root is None or not drive_root.exists():
        print("\n=== Google Drive 桌面版状态 ===")
        print("  [未挂载] 未检测到 Google Drive 本地挂载目录。")
        print("  下一步：运行自动下载与安装引导脚本：")
        print("    .venv/bin/python scripts/install_google_drive.py")
        return 0

    print(f"\n[OK] 检测到 Google Drive 挂载点: {drive_root}")
    studio_dir = get_studio_dir(drive_root, cfg)
    _inspect_studio(studio_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
