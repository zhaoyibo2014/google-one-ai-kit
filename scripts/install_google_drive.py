#!/usr/bin/env python3
"""Download and launch the official Google Drive for Desktop installer with guided setup."""

from __future__ import annotations

import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import find_google_drive_my_drive, load_config  # noqa: E402

INSTALLERS = {
    "Darwin": {
        "url": "https://dl.google.com/drive-file-stream/GoogleDrive.dmg",
        "filename": "GoogleDrive.dmg",
    },
    "Windows": {
        "url": "https://dl.google.com/drive-file-stream/GoogleDriveSetup.exe",
        "filename": "GoogleDriveSetup.exe",
    },
}


def _print_onboarding_guide() -> None:
    print("\n=== 安装与首次登录向导（务必按以下两步选，避免占满本地硬盘） ===")
    print("  1. 在安装向导登录你开通了 Google AI Pro / Google One 的谷歌账号。")
    print("  2. 出现「Choose folders to sync from your computer (同步本地文件夹)」时：")
    print("     👉 什么都不要勾选，直接点击右下角 [Skip]！")
    print("  3. 进入「See Drive files in Finder / Explorer」步骤时点 [Next] 完成：")
    print("     👉 默认即为 [Stream files (流式传输)] 模式，19 GB 云端模型只占云盘不占本地 SSD。")
    print("  4. 完成后重新运行: .venv/bin/python scripts/check_env.py")


def _is_app_installed(system: str) -> bool:
    if system == "Darwin":
        return Path("/Applications/Google Drive.app").exists()
    if system == "Windows":
        return Path("C:/Program Files/Google/Drive File Stream").exists()
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="检查或自动下载 Google Drive 桌面版官方安装包。")
    parser.add_argument("--dry-run", action="store_true", help="仅打印下载地址与路径，不执行下载")
    parser.add_argument("--no-open", action="store_true", help="只下载安装包，不自动打开")
    parser.add_argument("--force", action="store_true", help="即使已检测到安装也强制重新下载")
    args = parser.parse_args()

    cfg = load_config()
    mounted = find_google_drive_my_drive(config=cfg)
    if mounted is not None and mounted.exists() and not args.force:
        print(f"[OK] Google Drive 桌面版已安装并挂载: {mounted}")
        return 0

    system = platform.system()
    if system not in INSTALLERS:
        print(f"ℹ️ 当前系统 ({system}) 没有 Google Drive 官方桌面客户端。")
        print("请直接在浏览器使用 Google Drive + Colab，或自行使用 rclone 挂载。")
        return 0

    if _is_app_installed(system) and not args.force:
        print("[INFO] 检测到已安装 Google Drive 客户端，但尚未完成账号登录或挂载。")
        if system == "Darwin" and not args.no_open and not args.dry_run:
            subprocess.run(["open", "/Applications/Google Drive.app"], check=False)
        _print_onboarding_guide()
        return 0

    spec = INSTALLERS[system]
    downloads_dir = Path.home() / "Downloads"
    dst = downloads_dir / spec["filename"]

    if args.dry_run:
        print(f"[DRY-RUN] 系统: {system}")
        print(f"[DRY-RUN] 下载地址: {spec['url']}")
        print(f"[DRY-RUN] 保存路径: {dst}")
        _print_onboarding_guide()
        return 0

    curl_bin = shutil.which("curl")
    if not curl_bin:
        print(f"❌ 未找到 curl，请手动从浏览器下载: {spec['url']}", file=sys.stderr)
        return 1

    downloads_dir.mkdir(parents=True, exist_ok=True)
    print(f"⬇️ 正在下载 Google Drive 官方安装包 ({spec['url']}) -> {dst} ...")
    res = subprocess.run([curl_bin, "-fSL", "--progress-bar", spec["url"], "-o", str(dst)], check=False)
    if res.returncode != 0:
        print(f"❌ 下载失败（exit={res.returncode}），请检查网络或浏览器手动下载: {spec['url']}", file=sys.stderr)
        return res.returncode

    print(f"✅ 安装包已下载: {dst}")
    if not args.no_open:
        if system == "Darwin":
            subprocess.run(["open", str(dst)], check=False)
        elif system == "Windows":
            subprocess.Popen([str(dst)], shell=False)

    _print_onboarding_guide()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
