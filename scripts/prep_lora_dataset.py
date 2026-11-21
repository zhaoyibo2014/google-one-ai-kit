#!/usr/bin/env python3
"""Prepare curated style images + .txt captions for FLUX LoRA training."""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys
from PIL import Image, ImageOps

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (  # noqa: E402
    KIT_ROOT,
    SUPPORTED_IMAGE_EXTS,
    find_google_drive_my_drive,
    get_studio_dir,
    load_config,
)


def _round_dim_16(val: int, max_size: int) -> int:
    rounded = max(16, int(round(val / 16.0)) * 16)
    if rounded > max_size:
        rounded = max(16, (max_size // 16) * 16)
    return rounded


def _compute_target_size(w: int, h: int, max_size: int) -> tuple[int, int]:
    if max(w, h) > max_size:
        scale = max_size / float(max(w, h))
        w = int(round(w * scale))
        h = int(round(h * scale))
    return _round_dim_16(w, max_size), _round_dim_16(h, max_size)


def _prepare_caption(src_img: Path, dst_txt: Path, trigger: str) -> str:
    if dst_txt.exists():
        return "KEPT_EXISTING"

    src_txt = src_img.with_suffix(".txt")
    if src_txt.is_file():
        text = src_txt.read_text(encoding="utf-8").strip()
        if text and not text.lower().startswith(trigger.lower()):
            text = f"{trigger}, {text}"
        elif not text:
            text = f"{trigger}, stylized digital concept art, crisp lighting, high detail"
        dst_txt.write_text(text + "\n", encoding="utf-8")
        return "FROM_SOURCE_TXT"

    starter = (
        f"{trigger}, stylized digital concept art, "
        "clean composition, consistent shading and lighting, high detail\n"
    )
    dst_txt.write_text(starter, encoding="utf-8")
    return "CREATED_TEMPLATE"


def main() -> int:
    cfg = load_config()
    default_trigger = str(cfg.get("trigger_word") or "mystyle")
    default_ds = str(cfg.get("default_dataset_name") or "custom_style_v1")
    default_out = KIT_ROOT / "workspace" / "dataset" / default_ds

    parser = argparse.ArgumentParser(description="整理并标注 FLUX LoRA 训练集。")
    parser.add_argument("--input", required=True, type=Path, help="精选原图目录（仅放挑好画风的图片）")
    parser.add_argument("--output", type=Path, default=default_out, help=f"输出目录（默认: {default_out}）")
    parser.add_argument("--trigger", default=default_trigger, help=f"触发词（默认: {default_trigger}）")
    parser.add_argument("--max-size", type=int, default=1024, help="长边最大像素（默认 1024，会对齐 16 的倍数）")
    parser.add_argument("--min-size", type=int, default=512, help="短边最小像素阈值（默认 512）")
    parser.add_argument("--sync-to-drive", action="store_true", help="处理后同步到 Google Drive datasets/")
    parser.add_argument("--drive-root", help="可选：手动指定 Google Drive 'My Drive' 路径")
    args = parser.parse_args()

    in_dir = args.input.expanduser().resolve()
    out_dir = args.output.expanduser().resolve()
    if not in_dir.is_dir():
        print(f"❌ 输入目录不存在: {in_dir}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in in_dir.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_IMAGE_EXTS)
    if not files:
        print(f"❌ 在 {in_dir} 中未找到 PNG/JPG/WEBP 图片。", file=sys.stderr)
        return 1

    processed = 0
    skipped_small = 0

    for src in files:
        with Image.open(src) as raw:
            im = ImageOps.exif_transpose(raw)
            if min(im.width, im.height) < args.min_size:
                print(f"  [SKIP <{args.min_size}px] {src.name} ({im.width}x{im.height})")
                skipped_small += 1
                continue

            if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
                rgba = im.convert("RGBA")
                bg = Image.new("RGBA", rgba.size, (20, 25, 38, 255))
                im = Image.alpha_composite(bg, rgba).convert("RGB")
            else:
                im = im.convert("RGB")

            tw, th = _compute_target_size(im.width, im.height, args.max_size)
            if (tw, th) != (im.width, im.height):
                im = im.resize((tw, th), Image.Resampling.LANCZOS)

            dst_img = out_dir / f"{src.stem}.png"
            im.save(dst_img, format="PNG", optimize=True)

        cap_status = _prepare_caption(src, out_dir / f"{src.stem}.txt", args.trigger)
        processed += 1
        print(f"  [OK] {dst_img.name} ({tw}x{th}) | 标注: {cap_status}")

    print(f"\n处理完成: {processed} 张入库，跳过过小图片 {skipped_small} 张 -> {out_dir}")
    if processed < 15:
        print("⚠️ 当前样本数不足 15 张，建议凑够 15~25 张风格一致的图再开训 LoRA，效果更稳。")
    elif processed > 30:
        print("ℹ️ 样本超过 30 张，注意剔除画风不纯或崩坏的图（重质不重量）。")
    else:
        print("✅ 样本数量处于最佳区间 (15~25 张)，可以微调 .txt 描述后同步云端开训！")

    if args.sync_to_drive:
        drive_root = find_google_drive_my_drive(args.drive_root, cfg)
        if drive_root is None or not drive_root.exists():
            print("❌ 无法同步：未检测到 Google Drive 挂载目录。", file=sys.stderr)
            return 1
        dst_ds = get_studio_dir(drive_root, cfg) / "datasets" / out_dir.name
        dst_ds.mkdir(parents=True, exist_ok=True)
        copied = 0
        for p in sorted(out_dir.iterdir()):
            if p.is_file() and p.suffix.lower() in {".png", ".txt"}:
                shutil.copy2(p, dst_ds / p.name)
                copied += 1
        print(f"☁️ 已同步 {copied} 个文件到 Google Drive: {dst_ds}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
