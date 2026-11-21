#!/usr/bin/env python3
"""Extract Google Drive File IDs from mounted notebooks to generate direct Colab URLs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import find_google_drive_my_drive, get_studio_dir, load_config  # noqa: E402


def collect_colab_urls(studio_dir: Path) -> list[dict[str, str]]:
    """Return notebook metadata with direct https://colab.research.google.com/drive/<id> URLs."""
    nb_dir = studio_dir / "notebooks"
    if not nb_dir.is_dir():
        return []

    is_mac = platform.system() == "Darwin"
    results: list[dict[str, str]] = []
    for nb in sorted(nb_dir.glob("*.ipynb")):
        entry = {
            "name": nb.name,
            "path": str(nb),
            "file_id": "",
            "colab_url": "",
            "status": "unsupported_os" if not is_mac else "pending_upload",
        }
        if is_mac:
            proc = subprocess.run(
                ["xattr", "-p", "com.google.drivefs.item-id#S", str(nb)],
                capture_output=True,
                text=True,
                check=False,
            )
            file_id = proc.stdout.strip()
            if proc.returncode == 0 and file_id:
                entry["file_id"] = file_id
                entry["colab_url"] = f"https://colab.research.google.com/drive/{file_id}"
                entry["status"] = "ready"
        results.append(entry)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="读取 Google Drive 文件 ID 并生成 Colab 直达链接。")
    parser.add_argument("--drive-root", help="可选：手动指定 Google Drive 'My Drive' 路径")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出，方便 Agent 解析")
    args = parser.parse_args()

    cfg = load_config()
    drive_root = find_google_drive_my_drive(args.drive_root, cfg)
    if drive_root is None or not drive_root.exists():
        print("❌ 未检测到 Google Drive 挂载目录，请先运行 install_google_drive.py 或 check_env.py。", file=sys.stderr)
        return 1

    studio_dir = get_studio_dir(drive_root, cfg)
    rows = collect_colab_urls(studio_dir)

    if args.json:
        print(json.dumps({"studio_dir": str(studio_dir), "notebooks": rows}, indent=2, ensure_ascii=False))
        return 0

    if not rows:
        print(f"ℹ️ 在 {studio_dir / 'notebooks'} 未找到 .ipynb，请先运行 .venv/bin/python scripts/sync_to_drive.py")
        return 0

    print(f"=== Colab 笔记本直达链接 ({studio_dir / 'notebooks'}) ===")
    for row in rows:
        if row["colab_url"]:
            print(f"  [READY] {row['name']} -> {row['colab_url']}")
        elif row["status"] == "pending_upload":
            print(f"  [SYNCING] {row['name']} 尚未分配云端 File ID（请等待几秒让 Google Drive 完成上传后重试）")
        else:
            print(f"  [MANUAL] {row['name']} -> 请在浏览器 drive.google.com 进入 {studio_dir.name}/notebooks/ 双击打开")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
