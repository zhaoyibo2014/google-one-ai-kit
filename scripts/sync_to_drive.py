#!/usr/bin/env python3
"""Sync Colab notebooks, ComfyUI workflows, style reference images, and optional datasets to Google Drive."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (  # noqa: E402
    KIT_ROOT,
    STUDIO_SUBDIRS,
    SUPPORTED_IMAGE_EXTS,
    find_google_drive_my_drive,
    format_size,
    get_studio_dir,
    load_config,
    resolve_anchor_path,
)


def _needs_copy(src: Path, dst: Path, force: bool) -> bool:
    if force or not dst.exists():
        return True
    s_stat = src.stat()
    d_stat = dst.stat()
    if s_stat.st_size != d_stat.st_size:
        return True
    return abs(s_stat.st_mtime - d_stat.st_mtime) > 2.0


def _copy_file(src: Path, dst: Path, force: bool, dry_run: bool) -> str:
    if not _needs_copy(src, dst, force):
        return "SKIP"
    if dry_run:
        return "DRY_RUN"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return "COPIED"


def main() -> int:
    parser = argparse.ArgumentParser(description="将 Google One AI Kit 文件同步至 Google Drive。")
    parser.add_argument("--drive-root", help="手动指定 Google Drive 'My Drive' 路径（测试或自定义挂载时使用）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览将同步的文件，不实际写入")
    parser.add_argument("--force", action="store_true", help="强制覆盖云端已有文件")
    parser.add_argument("--include-dataset", action="store_true", help="同时同步本地整理好的 LoRA 训练集")
    args = parser.parse_args()

    cfg = load_config()
    drive_root = find_google_drive_my_drive(args.drive_root, cfg)
    if drive_root is None:
        print("❌ 未检测到 Google Drive 桌面版挂载目录。")
        print("请先运行 .venv/bin/python scripts/install_google_drive.py，或用 --drive-root 指定路径。", file=sys.stderr)
        return 1

    if not args.dry_run:
        drive_root.mkdir(parents=True, exist_ok=True)

    studio_dir = get_studio_dir(drive_root, cfg)
    dataset_name = str(cfg.get("default_dataset_name") or "custom_style_v1")

    print(f"目标 Google Drive 目录: {studio_dir}")
    if args.dry_run:
        print("[DRY-RUN 模式：不修改磁盘]")

    if not args.dry_run:
        for sub in STUDIO_SUBDIRS:
            (studio_dir / sub).mkdir(parents=True, exist_ok=True)
        (studio_dir / "datasets" / dataset_name).mkdir(parents=True, exist_ok=True)

    plan: list[tuple[Path, Path]] = []

    for nb in sorted((KIT_ROOT / "notebooks").glob("*.ipynb")):
        plan.append((nb, studio_dir / "notebooks" / nb.name))

    for wf in sorted((KIT_ROOT / "workflows").glob("*.json")):
        plan.append((wf, studio_dir / "workflows" / wf.name))

    seen_refs: set[str] = set()
    for target_name, raw_path in (cfg.get("style_anchors") or {}).items():
        src = resolve_anchor_path(raw_path)
        if not src.is_file():
            print(f"⚠️ 跳过缺失的风格参考图: {src}", file=sys.stderr)
            continue
        plan.append((src, studio_dir / "input_refs" / target_name))
        seen_refs.add(target_name)

    refs_dir = KIT_ROOT / "workspace" / "style_refs"
    if refs_dir.is_dir():
        for ref_img in sorted(refs_dir.iterdir()):
            if (
                ref_img.is_file()
                and ref_img.suffix.lower() in SUPPORTED_IMAGE_EXTS
                and ref_img.name not in seen_refs
            ):
                plan.append((ref_img, studio_dir / "input_refs" / ref_img.name))

    if args.include_dataset:
        local_ds = KIT_ROOT / "workspace" / "dataset" / dataset_name
        if local_ds.is_dir():
            for item in sorted(local_ds.iterdir()):
                if item.is_file() and not item.name.startswith("."):
                    plan.append((item, studio_dir / "datasets" / dataset_name / item.name))
        else:
            print(f"⚠️ 未找到本地训练集目录: {local_ds}（可先运行 prep_lora_dataset.py）")

    counts = {"COPIED": 0, "SKIP": 0, "DRY_RUN": 0}
    for src, dst in plan:
        status = _copy_file(src, dst, args.force, args.dry_run)
        counts[status] += 1
        rel_dst = dst.relative_to(studio_dir)
        print(f"  [{status:7s}] {rel_dst} ({format_size(src.stat().st_size)})")

    print(
        f"\n完成：新增/更新 {counts['COPIED']} 个，跳过未变更 {counts['SKIP']} 个"
        + (f"，预演 {counts['DRY_RUN']} 个" if args.dry_run else "")
        + "。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
