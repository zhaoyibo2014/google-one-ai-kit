#!/usr/bin/env python3
"""CLI-automated FLUX + multi-Redux ComfyUI runner powered by google-colab-cli."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (  # noqa: E402
    KIT_ROOT,
    find_google_drive_my_drive,
    get_studio_dir,
    load_config,
)

REMOTE_RUNNER_CODE = r'''
import json
import os
import random
import shutil
import subprocess
import sys
import time
import urllib.request

SPEC_PATH = "/content/studio_job_spec.json"
COMFY_DIR = "/content/ComfyUI"
REFS_STAGE = "/content/job_refs"
OUT_DIR = "/content/job_outputs"
LOG_PATH = "/content/comfyui_cli.log"

os.makedirs(OUT_DIR, exist_ok=True)
with open(SPEC_PATH, "r", encoding="utf-8") as f:
    spec = json.load(f)

if not os.path.exists(COMFY_DIR):
    print("Cloning ComfyUI...", flush=True)
    subprocess.run(
        ["git", "clone", "--depth", "1", "https://github.com/comfyanonymous/ComfyUI.git", COMFY_DIR],
        check=True,
    )

print("Ensuring ComfyUI + huggingface_hub dependencies...", flush=True)
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "-r", f"{COMFY_DIR}/requirements.txt"],
    check=True,
)
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "-U", "huggingface_hub[hf_transfer]"],
    check=True,
)
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

from huggingface_hub import hf_hub_download

MODELS = [
    ("Comfy-Org/Flux-1-Dev", "flux1-dev-fp8.safetensors", f"{COMFY_DIR}/models/checkpoints"),
    ("Comfy-Org/Flux-1-Redux-Dev", "flux1-redux-dev.safetensors", f"{COMFY_DIR}/models/style_models"),
    ("Comfy-Org/sigclip_vision_384", "sigclip_vision_patch14_384.safetensors", f"{COMFY_DIR}/models/clip_vision"),
]
for repo_id, filename, target_dir in MODELS:
    os.makedirs(target_dir, exist_ok=True)
    target_path = os.path.join(target_dir, filename)
    if os.path.exists(target_path) and os.path.getsize(target_path) > 50 * 1024 * 1024:
        print(f"[SKIP] {filename} already present", flush=True)
        continue
    print(f"[DOWNLOAD] {repo_id}/{filename} ...", flush=True)
    hf_hub_download(repo_id=repo_id, filename=filename, local_dir=target_dir)

in_dir = f"{COMFY_DIR}/input"
os.makedirs(in_dir, exist_ok=True)
if os.path.isdir(REFS_STAGE):
    for name in os.listdir(REFS_STAGE):
        src = os.path.join(REFS_STAGE, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(in_dir, name))

log_f = open(LOG_PATH, "w", encoding="utf-8")
comfy_proc = subprocess.Popen(
    [
        sys.executable,
        "main.py",
        "--listen", "127.0.0.1",
        "--port", "8188",
        "--output-directory", OUT_DIR,
    ],
    cwd=COMFY_DIR,
    stdout=log_f,
    stderr=subprocess.STDOUT,
)

try:
    ready = False
    for _ in range(90):
        if comfy_proc.poll() is not None:
            log_f.flush()
            with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as rf:
                raise RuntimeError("ComfyUI exited early:\n" + "".join(rf.readlines()[-60:]))
        try:
            with urllib.request.urlopen("http://127.0.0.1:8188/system_stats", timeout=2) as r:
                if r.status == 200:
                    ready = True
                    break
        except Exception:
            pass
        time.sleep(2)
    if not ready:
        raise TimeoutError("ComfyUI failed to become ready within 180s")

    print("ComfyUI ready on 127.0.0.1:8188", flush=True)
    generated_files = []

    def build_api_prompt(job, seed):
        prompt = {
            "1": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {"ckpt_name": "flux1-dev-fp8.safetensors"},
            },
            "2": {
                "class_type": "CLIPTextEncode",
                "inputs": {"text": job["prompt"], "clip": ["1", 1]},
            },
            "3": {
                "class_type": "FluxGuidance",
                "inputs": {"guidance": float(job.get("guidance", 3.4)), "conditioning": ["2", 0]},
            },
            "4": {
                "class_type": "ConditioningZeroOut",
                "inputs": {"conditioning": ["2", 0]},
            },
            "5": {
                "class_type": "EmptySD3LatentImage",
                "inputs": {
                    "width": int(job.get("width", 1024)),
                    "height": int(job.get("height", 1536)),
                    "batch_size": 1,
                },
            },
        }
        cond_node = "3"
        next_id = 10
        refs = job.get("refs") or []
        if refs:
            prompt["6"] = {
                "class_type": "CLIPVisionLoader",
                "inputs": {"clip_name": "sigclip_vision_patch14_384.safetensors"},
            }
            prompt["7"] = {
                "class_type": "StyleModelLoader",
                "inputs": {"style_model_name": "flux1-redux-dev.safetensors"},
            }
            for ref_name, strength in refs:
                load_id = str(next_id)
                enc_id = str(next_id + 1)
                apply_id = str(next_id + 2)
                next_id += 3
                prompt[load_id] = {
                    "class_type": "LoadImage",
                    "inputs": {"image": ref_name},
                }
                prompt[enc_id] = {
                    "class_type": "CLIPVisionEncode",
                    "inputs": {"clip_vision": ["6", 0], "image": [load_id, 0], "crop": "center"},
                }
                prompt[apply_id] = {
                    "class_type": "StyleModelApply",
                    "inputs": {
                        "conditioning": [cond_node, 0],
                        "style_model": ["7", 0],
                        "clip_vision_output": [enc_id, 0],
                        "strength": float(strength),
                        "strength_type": "multiply",
                    },
                }
                cond_node = apply_id

        prompt["90"] = {
            "class_type": "KSampler",
            "inputs": {
                "seed": int(seed),
                "steps": int(job.get("steps", 24)),
                "cfg": 1.0,
                "sampler_name": "euler",
                "scheduler": "simple",
                "denoise": 1.0,
                "model": ["1", 0],
                "positive": [cond_node, 0],
                "negative": ["4", 0],
                "latent_image": ["5", 0],
            },
        }
        prompt["91"] = {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["90", 0], "vae": ["1", 2]},
        }
        prompt["92"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": job.get("prefix", "cli_gen"), "images": ["91", 0]},
        }
        return prompt

    for j_idx, job in enumerate(spec["jobs"], 1):
        count = int(job.get("count", 1))
        base_seed = job.get("seed")
        for i in range(count):
            seed = (int(base_seed) + i) if base_seed is not None else random.randint(1, 2**31 - 1)
            payload = json.dumps({"prompt": build_api_prompt(job, seed)}).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8188/prompt",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                queued = json.loads(resp.read().decode("utf-8"))
            prompt_id = queued["prompt_id"]
            print(f"[Job {j_idx} {i+1}/{count}] Queued prompt_id={prompt_id} prefix={job.get('prefix')} seed={seed}", flush=True)

            done = False
            for tick in range(360):
                with urllib.request.urlopen(f"http://127.0.0.1:8188/history/{prompt_id}", timeout=10) as hresp:
                    hist = json.loads(hresp.read().decode("utf-8"))
                if prompt_id in hist:
                    entry = hist[prompt_id]
                    status_info = entry.get("status") or {}
                    if status_info.get("status_str") == "error":
                        raise RuntimeError(f"ComfyUI execution error: {status_info}")
                    outputs = entry.get("outputs") or {}
                    for node_out in outputs.values():
                        for img_meta in node_out.get("images", []):
                            fname = img_meta["filename"]
                            sub = img_meta.get("subfolder") or ""
                            rel = os.path.join(sub, fname) if sub else fname
                            generated_files.append(rel)
                            print(f"  [GENERATED] {rel}", flush=True)
                    done = True
                    break
                if tick > 0 and tick % 10 == 0:
                    print(f"  ... waiting ({tick * 2}s)", flush=True)
                time.sleep(2)
            if not done:
                raise TimeoutError(f"Timed out waiting for prompt_id={prompt_id}")

    with open(f"{OUT_DIR}/manifest.json", "w", encoding="utf-8") as mf:
        json.dump({"files": generated_files}, mf, indent=2)
    print(f"ALL {len(generated_files)} IMAGES COMPLETED.", flush=True)
finally:
    comfy_proc.terminate()
    try:
        comfy_proc.wait(timeout=10)
    except Exception:
        comfy_proc.kill()
    log_f.close()
'''


def _find_colab_bin() -> str:
    found = shutil.which("colab")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "colab"
    if candidate.is_file():
        return str(candidate)
    raise FileNotFoundError(
        "未找到 colab CLI（需要 Python >= 3.12）。请先运行: uv tool install --python 3.12 google-colab-cli"
    )


def _run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("$", " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True)


def _parse_ref_arg(raw: str) -> tuple[Path, float]:
    if ":" not in raw:
        raise ValueError(f"--ref 格式应为 <图片路径>:<强度>，实际收到: {raw}")
    path_str, strength_str = raw.rsplit(":", 1)
    p = Path(path_str).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"找不到参考图: {p}")
    return p, float(strength_str)


def main() -> int:
    parser = argparse.ArgumentParser(description="纯命令行全自动驱动 Colab GPU + ComfyUI 出图（0 浏览器、用完自动关机）。")
    parser.add_argument("--gpu", default="L4", help="Colab GPU 类型（默认 L4）")
    parser.add_argument("--session", default="studio-gen", help="Colab 会话名（默认 studio-gen）")
    parser.add_argument("--job-json", type=Path, help="多批次任务 JSON 文件路径")
    parser.add_argument("--prompt", help="单批次英文自然语言 Prompt")
    parser.add_argument("--ref", action="append", default=[], help="Redux 参考图与强度，格式 <路径>:<强度>，可多次传入实现多图融合")
    parser.add_argument("--prefix", default="cli_gen", help="输出文件名前缀")
    parser.add_argument("--count", type=int, default=2, help="生成张数（默认 2）")
    parser.add_argument("--width", type=int, default=1024, help="图像宽度（默认 1024）")
    parser.add_argument("--height", type=int, default=1536, help="图像高度（默认 1536）")
    parser.add_argument("--steps", type=int, default=24, help="采样步数（默认 24）")
    parser.add_argument("--guidance", type=float, default=3.4, help="FluxGuidance 强度（默认 3.4）")
    parser.add_argument("--seed", type=int, default=None, help="可选固定起始随机种子")
    parser.add_argument("--out-dir", type=Path, default=KIT_ROOT / "workspace" / "outputs", help="本地输出目录")
    parser.add_argument("--keep", action="store_true", help="完成后保留 Colab VM（默认会自动 stop 防止扣点数）")
    args = parser.parse_args()

    if not args.job_json and not args.prompt:
        parser.error("必须提供 --job-json 或 --prompt。")

    colab_bin = _find_colab_bin()
    raw_jobs: list[dict] = []
    if args.job_json:
        loaded = json.loads(args.job_json.expanduser().resolve().read_text(encoding="utf-8"))
        raw_jobs = loaded["jobs"] if isinstance(loaded, dict) and "jobs" in loaded else loaded
    else:
        refs = [_parse_ref_arg(r) for r in args.ref]
        raw_jobs = [
            {
                "prompt": args.prompt,
                "prefix": args.prefix,
                "count": args.count,
                "width": args.width,
                "height": args.height,
                "steps": args.steps,
                "guidance": args.guidance,
                "seed": args.seed,
                "refs": [[str(p), s] for p, s in refs],
            }
        ]

    unique_refs: dict[str, Path] = {}
    remote_jobs: list[dict] = []
    for job in raw_jobs:
        norm_refs = []
        for item in job.get("refs") or []:
            p = Path(item[0]).expanduser().resolve()
            if not p.is_file():
                raise FileNotFoundError(f"找不到参考图: {p}")
            unique_refs[p.name] = p
            norm_refs.append([p.name, float(item[1])])
        j_copy = dict(job)
        j_copy["refs"] = norm_refs
        remote_jobs.append(j_copy)

    out_dir = args.out_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    drive_outputs: Path | None = None
    cfg = load_config()
    drive_root = find_google_drive_my_drive(config=cfg)
    if drive_root and drive_root.exists():
        drive_outputs = get_studio_dir(drive_root, cfg) / "outputs"
        drive_outputs.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="studio_cli_") as tmp:
        tmp_dir = Path(tmp)
        spec_path = tmp_dir / "studio_job_spec.json"
        runner_path = tmp_dir / "studio_remote_runner.py"
        manifest_local = tmp_dir / "manifest.json"
        spec_path.write_text(json.dumps({"jobs": remote_jobs}, indent=2, ensure_ascii=False), encoding="utf-8")
        runner_path.write_text(REMOTE_RUNNER_CODE, encoding="utf-8")

        _run_cmd([colab_bin, "new", "-s", args.session, "--gpu", args.gpu])
        try:
            subprocess.run(
                [colab_bin, "exec", "-s", args.session, "--timeout", "60"],
                input="import os; os.makedirs('/content/job_refs', exist_ok=True); os.makedirs('/content/job_outputs', exist_ok=True)\n",
                text=True,
                check=True,
            )
            _run_cmd([colab_bin, "upload", "-s", args.session, str(spec_path), "/content/studio_job_spec.json"])
            for ref_name, ref_path in unique_refs.items():
                _run_cmd([colab_bin, "upload", "-s", args.session, str(ref_path), f"/content/job_refs/{ref_name}"])

            _run_cmd([colab_bin, "exec", "-s", args.session, "--timeout", "0", "-f", str(runner_path)])
            _run_cmd([colab_bin, "download", "-s", args.session, "/content/job_outputs/manifest.json", str(manifest_local)])

            manifest = json.loads(manifest_local.read_text(encoding="utf-8"))
            files = manifest.get("files") or []
            print(f"\n⬇️ 正在拉回 {len(files)} 张成品到本地: {out_dir}")
            for rel in files:
                fname = Path(rel).name
                local_dst = out_dir / fname
                _run_cmd([colab_bin, "download", "-s", args.session, f"/content/job_outputs/{rel}", str(local_dst)])
                if drive_outputs:
                    shutil.copy2(local_dst, drive_outputs / fname)
            if drive_outputs:
                print(f"☁️ 已同步镜像到 Google Drive: {drive_outputs}")
        finally:
            if not args.keep:
                print(f"\n🛑 自动关停 Colab 会话 {args.session}（防止额外扣点数）...")
                _run_cmd([colab_bin, "stop", "-s", args.session], check=False)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
