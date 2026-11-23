#!/usr/bin/env python3
"""Headless 2D-to-3D runner on Colab L4 powered by google-colab-cli (TRELLIS.2 & Hunyuan3D-2mv).

Provisions an isolated Python 3.11 + CUDA 12.4.1 + GCC 12 + PyTorch 2.6.0+cu124 environment
via micromamba inside the Colab VM so CUDA extensions (o_voxel, cumesh, flex_gemm, nvdiffrast,
custom_rasterizer) compile cleanly regardless of Colab's default Python 3.13 / CUDA 13.0 image.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (  # noqa: E402
    KIT_ROOT,
    find_google_drive_my_drive,
    get_studio_dir,
    load_config,
)

TRELLIS2_GATED_REPOS = (
    ("facebook/dinov3-vitl16-pretrain-lvd1689m", "manual review (Meta)"),
    ("briaai/RMBG-2.0", "auto-approve upon clicking Agree"),
)

REMOTE_BOOTSTRAP_CODE = r'''
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

STATUS_PATH = Path("/content/job_status.txt")
INNER_SCRIPT = "__INNER_SCRIPT__"
ENV_PREFIX = Path("/opt/mamba3d")


def ensure_isolated_env() -> dict[str, str]:
    if not Path("/usr/local/bin/micromamba").is_file():
        print("Installing micromamba ...", flush=True)
        subprocess.run(
            [
                "bash",
                "-lc",
                "curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj -C /usr/local/bin --strip-components=1 bin/micromamba",
            ],
            check=True,
        )

    py_bin = ENV_PREFIX / "bin" / "python"
    pip_bin = ENV_PREFIX / "bin" / "pip"
    if not py_bin.is_file():
        print("Creating isolated Python 3.11 + CUDA 12.4.1 + GCC 12 environment (/opt/mamba3d) ...", flush=True)
        subprocess.run(
            [
                "/usr/local/bin/micromamba",
                "create",
                "-y",
                "-p",
                str(ENV_PREFIX),
                "-c",
                "nvidia/label/cuda-12.4.1",
                "-c",
                "conda-forge",
                "python=3.11",
                "pip",
                "ninja",
                "gcc_linux-64=12",
                "gxx_linux-64=12",
                "cuda-toolkit=12.4.1",
            ],
            check=True,
        )
        print("Installing PyTorch 2.6.0+cu124 into /opt/mamba3d ...", flush=True)
        subprocess.run(
            [
                str(pip_bin),
                "install",
                "-q",
                "--no-cache-dir",
                "torch==2.6.0",
                "torchvision==0.21.0",
                "--index-url",
                "https://download.pytorch.org/whl/cu124",
            ],
            check=True,
        )

    env = os.environ.copy()
    env["CONDA_PREFIX"] = str(ENV_PREFIX)
    env["CUDA_HOME"] = str(ENV_PREFIX)
    env["PATH"] = f"{ENV_PREFIX / 'bin'}:{env.get('PATH', '')}"
    torch_lib = ENV_PREFIX / "lib" / "python3.11" / "site-packages" / "torch" / "lib"
    env["LD_LIBRARY_PATH"] = f"{ENV_PREFIX / 'lib'}:{torch_lib}:{env.get('LD_LIBRARY_PATH', '')}"
    env["TORCH_CUDA_ARCH_LIST"] = "8.9"
    env["MAX_JOBS"] = "4"
    env["MPLBACKEND"] = "Agg"

    gcc_bin = ENV_PREFIX / "bin" / "x86_64-conda-linux-gnu-gcc"
    gxx_bin = ENV_PREFIX / "bin" / "x86_64-conda-linux-gnu-g++"
    if gcc_bin.is_file() and gxx_bin.is_file():
        env["CC"] = str(gcc_bin)
        env["CXX"] = str(gxx_bin)
        env["CUDAHOSTCXX"] = str(gxx_bin)

    spec_file = Path("/content/job_spec.json")
    if spec_file.is_file():
        spec_data = json.loads(spec_file.read_text(encoding="utf-8"))
        hf_tok = (spec_data.get("hf_token") or "").strip()
        if hf_tok:
            env["HF_TOKEN"] = hf_tok
            env["HUGGING_FACE_HUB_TOKEN"] = hf_tok

    return env


if __name__ == "__main__":
    try:
        if STATUS_PATH.exists():
            STATUS_PATH.unlink()
        iso_env = ensure_isolated_env()
        py_bin = str(ENV_PREFIX / "bin" / "python")
        subprocess.run([py_bin, "-u", INNER_SCRIPT], env=iso_env, check=True)
        STATUS_PATH.write_text("DONE\n", encoding="utf-8")
    except Exception:
        err = traceback.format_exc()
        print(err, flush=True)
        STATUS_PATH.write_text("ERROR\n" + err, encoding="utf-8")
        raise SystemExit(1)
'''

REMOTE_TRELLIS2_CODE = r'''
import gc
import glob
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ["OPENCV_IO_ENABLE_OPENEXR"] = "1"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["MPLBACKEND"] = "Agg"
os.environ["ATTN_BACKEND"] = "sdpa"
os.environ["SPARSE_ATTN_BACKEND"] = "xformers"

SPEC_PATH = "/content/job_spec.json"
OUT_DIR = Path("/content/job_outputs")
OUT_DIR.mkdir(parents=True, exist_ok=True)
TRELLIS_DIR = Path("/content/TRELLIS.2")


def run_job():
    with open(SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    subprocess.run(["bash", "-lc", "which nvcc; nvcc --version; python --version"], check=False)

    if not TRELLIS_DIR.exists():
        print("Cloning microsoft/TRELLIS.2 ...", flush=True)
        subprocess.run(
            ["git", "clone", "-b", "main", "https://github.com/microsoft/TRELLIS.2.git", "--recursive", str(TRELLIS_DIR)],
            check=True,
        )

    stamp = TRELLIS_DIR / ".setup_done"
    if not stamp.exists():
        setup_sh = TRELLIS_DIR / "setup.sh"
        setup_text = setup_sh.read_text(encoding="utf-8") if setup_sh.is_file() else ""
        # Skip --flash-attn to avoid long source compilation on L4; use xformers + SDPA instead.
        flags = ["--basic", "--o-voxel", "--flexgemm", "--nvdiffrast"]
        for opt in ("--cumesh", "--nvdiffrec"):
            if opt in setup_text:
                flags.append(opt)
        print("Running TRELLIS.2 setup.sh:", " ".join(flags), flush=True)
        subprocess.run(["bash", "setup.sh", *flags], cwd=str(TRELLIS_DIR), check=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "rembg", "imageio[ffmpeg]", "opencv-python-headless", "pygltflib"],
            check=False,
        )
        # Pin transformers 4.57.6: transformers 5.x refactored DINOv3ViTModel and removed `.layer`,
        # which breaks trellis2/modules/image_feature_extractor.py.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-q",
                "transformers==4.57.6",
                "huggingface-hub>=0.34.0,<1.0.0",
                "tokenizers>=0.22.0,<=0.23.0",
            ],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "-c",
                "from transformers import DINOv3ViTModel, DINOv3ViTConfig; "
                "m = DINOv3ViTModel(DINOv3ViTConfig(num_hidden_layers=1)); "
                "assert hasattr(m, 'layer'), dir(m); print('DINOV3_LAYER_OK')",
            ],
            check=True,
        )
        # Install official xformers wheel built for torch==2.6.0 + cp311 (~5s, zero compilation)
        # for TRELLIS.2 sparse attention (`SPARSE_ATTN_BACKEND=xformers`).
        print("Installing xformers==0.0.29.post3 (--no-deps) ...", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--no-deps", "xformers==0.0.29.post3"],
            check=True,
        )
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import torch, xformers.ops as xops; "
                "q = torch.randn(1, 8, 4, 64, device='cuda', dtype=torch.float16); "
                "out = xops.memory_efficient_attention(q, q, q); "
                "print('XFORMERS_CUDA_OK', tuple(out.shape))",
            ],
            check=True,
        )
        stamp.write_text("ok", encoding="utf-8")

    if str(TRELLIS_DIR) not in sys.path:
        sys.path.insert(0, str(TRELLIS_DIR))

    import cv2
    import imageio
    from PIL import Image
    import torch
    from trellis2.pipelines import Trellis2ImageTo3DPipeline
    from trellis2.utils import render_utils
    from trellis2.renderers import EnvMap
    import o_voxel

    front_candidates = sorted(glob.glob("/content/job_input/front.*"))
    if not front_candidates:
        raise FileNotFoundError("Missing /content/job_input/front.*")
    front_path = Path(front_candidates[0])
    print(f"Using input: {front_path}", flush=True)

    print("Loading microsoft/TRELLIS.2-4B ...", flush=True)
    pipeline = Trellis2ImageTo3DPipeline.from_pretrained("microsoft/TRELLIS.2-4B")
    pipeline.cuda()

    image = Image.open(front_path).convert("RGB")
    seed = int(spec.get("seed", 42))
    run_sig = inspect.signature(pipeline.run)
    print("Running TRELLIS.2-4B inference ...", flush=True)
    if "seed" in run_sig.parameters:
        mesh = pipeline.run(image, seed=seed)[0]
    else:
        torch.manual_seed(seed)
        mesh = pipeline.run(image)[0]

    mesh.simplify(16777216)

    generated = []
    decimation_target = int(spec.get("target_faces", 60000))
    texture_size = int(spec.get("texture_size", 2048))
    print(f"Exporting PBR GLB (faces={decimation_target}, tex={texture_size}) ...", flush=True)
    glb = o_voxel.postprocess.to_glb(
        vertices=mesh.vertices,
        faces=mesh.faces,
        attr_volume=mesh.attrs,
        coords=mesh.coords,
        attr_layout=mesh.layout,
        voxel_size=mesh.voxel_size,
        aabb=[[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        decimation_target=decimation_target,
        texture_size=texture_size,
        remesh=True,
        remesh_band=1,
        remesh_project=0,
        verbose=True,
    )
    glb_path = OUT_DIR / "trellis2_pbr.glb"
    try:
        glb.export(str(glb_path), extension_webp=False)
    except TypeError:
        glb.export(str(glb_path))
    generated.append("trellis2_pbr.glb")

    try:
        hdri_path = TRELLIS_DIR / "assets" / "hdri" / "forest.exr"
        hdri_bgr = cv2.imread(str(hdri_path), cv2.IMREAD_UNCHANGED) if hdri_path.is_file() else None
        if hdri_bgr is not None:
            envmap_tensor = torch.tensor(cv2.cvtColor(hdri_bgr, cv2.COLOR_BGR2RGB), dtype=torch.float32, device="cuda")
        else:
            print("⚠️ OpenCV failed to read forest.exr; using synthetic studio EnvMap fallback", flush=True)
            grad = torch.linspace(1.2, 0.6, 128, dtype=torch.float32, device="cuda").view(128, 1, 1)
            envmap_tensor = grad.expand(128, 256, 3).contiguous()
        print("Rendering PBR turntable video ...", flush=True)
        envmap = EnvMap(envmap_tensor)
        frames = render_utils.make_pbr_vis_frames(render_utils.render_video(mesh, envmap=envmap))
        mp4_path = OUT_DIR / "trellis2_preview.mp4"
        imageio.mimsave(str(mp4_path), frames, fps=15)
        generated.append("trellis2_preview.mp4")

        if len(frames) >= 4:
            picks = [0, len(frames) // 4, len(frames) // 2, (len(frames) * 3) // 4]
            pil_frames = [Image.fromarray(frames[idx]) for idx in picks]
            w, h = pil_frames[0].size
            grid = Image.new("RGB", (w * len(pil_frames), h))
            for i, im in enumerate(pil_frames):
                grid.paste(im, (i * w, 0))
            grid.save(OUT_DIR / "trellis2_preview_grid.png")
            generated.append("trellis2_preview_grid.png")
    except Exception as preview_exc:
        print(f"⚠️ Preview render skipped: {preview_exc}", flush=True)

    with open(OUT_DIR / "manifest.json", "w", encoding="utf-8") as mf:
        json.dump({"files": generated}, mf, indent=2)

    del pipeline, mesh, glb
    gc.collect()
    torch.cuda.empty_cache()
    print("TRELLIS.2 JOB COMPLETED:", generated, flush=True)


if __name__ == "__main__":
    run_job()
'''

REMOTE_HUNYUAN3D_CODE = r'''
import gc
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
os.environ["MPLBACKEND"] = "Agg"

SPEC_PATH = "/content/job_spec.json"
OUT_DIR = Path("/content/job_outputs")
VIEWS_DIR = OUT_DIR / "views"
OUT_DIR.mkdir(parents=True, exist_ok=True)
VIEWS_DIR.mkdir(parents=True, exist_ok=True)

MV_DIR = Path("/content/MV-Adapter")
HY_DIR = Path("/content/Hunyuan3D-2")


def install_filtered_reqs(req_path: Path):
    if not req_path.is_file():
        return
    keep = []
    skip = ("torch", "torchvision", "torchaudio", "xformers")
    for raw in req_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if "nvdiffrast" in low:
            continue
        if any(low.startswith(p) and (len(low) == len(p) or low[len(p)] in "=<>!~ [") for p in skip):
            continue
        keep.append(line)
    if keep:
        tmp = Path("/tmp") / f"reqs_{req_path.parent.name}.txt"
        tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(tmp)], check=False)


def run_job():
    with open(SPEC_PATH, "r", encoding="utf-8") as f:
        spec = json.load(f)

    subprocess.run(["bash", "-lc", "which nvcc; nvcc --version; python --version"], check=False)

    if not MV_DIR.exists():
        print("Cloning MV-Adapter ...", flush=True)
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/huanngzh/MV-Adapter.git", str(MV_DIR)], check=True)
    if not HY_DIR.exists():
        print("Cloning Hunyuan3D-2 ...", flush=True)
        subprocess.run(["git", "clone", "--depth", "1", "https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git", str(HY_DIR)], check=True)

    pkgs = [
        "diffusers==0.31.0",
        "transformers==4.46.3",
        "accelerate>=0.34.0,<1.5.0",
        "huggingface_hub>=0.25.0,<1.0.0",
        "einops",
        "omegaconf",
        "safetensors",
        "trimesh",
        "pymeshlab",
        "pygltflib",
        "xatlas",
        "scikit-image",
        "opencv-python-headless",
        "rembg[gpu]",
        "onnxruntime-gpu",
        "ninja",
        "pybind11",
        "pillow",
        "matplotlib",
        "scipy",
        "imageio",
        "timm",
        "pyyaml",
        "jaxtyping",
        "typeguard",
        "kiui",
    ]
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *pkgs], check=True)
    except subprocess.CalledProcessError:
        fb = [p for p in pkgs if p not in {"rembg[gpu]", "onnxruntime-gpu"}] + ["rembg", "onnxruntime"]
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", *fb], check=True)

    install_filtered_reqs(MV_DIR / "requirements.txt")
    install_filtered_reqs(HY_DIR / "requirements.txt")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "transformers==4.46.3", "diffusers==0.31.0", "huggingface_hub>=0.25.0,<1.0.0"],
        check=True,
    )
    subprocess.run(
        [sys.executable, "-c", "import transformers, diffusers; print('PINNED VERSIONS:', transformers.__version__, diffusers.__version__)"],
        check=True,
    )
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-deps", "-e", str(HY_DIR)], check=True)

    stamp = HY_DIR / ".cuda_ext_built"
    if not stamp.exists():
        cr_dir = HY_DIR / "hy3dgen" / "texgen" / "custom_rasterizer"
        if cr_dir.is_dir():
            print("Building CUDA ext (non-editable): custom_rasterizer ...", flush=True)
            subprocess.run(
                [sys.executable, "-m", "pip", "install", ".", "--no-build-isolation", "--no-deps"],
                cwd=str(cr_dir),
                check=True,
            )

        dr_dir = HY_DIR / "hy3dgen" / "texgen" / "differentiable_renderer"
        if dr_dir.is_dir():
            if (dr_dir / "compile_mesh_painter.sh").is_file():
                print("Running compile_mesh_painter.sh ...", flush=True)
                subprocess.run(["bash", "compile_mesh_painter.sh"], cwd=str(dr_dir), check=True)
            if (dr_dir / "setup.py").is_file() or (dr_dir / "pyproject.toml").is_file():
                print("Building CUDA ext (non-editable): differentiable_renderer ...", flush=True)
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", ".", "--no-build-isolation", "--no-deps"],
                    cwd=str(dr_dir),
                    check=True,
                )

        print("Installing nvdiffrast (--no-build-isolation) ...", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "--no-build-isolation", "git+https://github.com/NVlabs/nvdiffrast.git"],
            check=True,
        )
        stamp.write_text("ok", encoding="utf-8")

    subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys, torch; sys.path.insert(0, {str(HY_DIR)!r}); import custom_rasterizer; from hy3dgen.texgen import Hunyuan3DPaintPipeline; print('CUSTOM_RASTERIZER_OK:', custom_rasterizer.__file__)",
        ],
        check=True,
    )

    from PIL import Image, ImageDraw
    import torch
    import trimesh
    from rembg import remove as rembg_remove

    front_candidates = sorted(glob.glob("/content/job_input/front.*"))
    if not front_candidates:
        raise FileNotFoundError("Missing /content/job_input/front.*")
    front_src = Path(front_candidates[0])

    def prepare_centered(src: Path, size: int = 768):
        raw = Image.open(src).convert("RGBA")
        cut = rembg_remove(raw)
        bbox = cut.getbbox()
        if bbox:
            cut = cut.crop(bbox)
        max_inner = int(size * 0.88)
        scale = min(max_inner / cut.width, max_inner / cut.height)
        nw, nh = max(1, int(round(cut.width * scale))), max(1, int(round(cut.height * scale)))
        rs = cut.resize((nw, nh), Image.Resampling.LANCZOS)
        rgba = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        rgba.paste(rs, ((size - nw) // 2, (size - nh) // 2), rs)
        white = Image.new("RGBA", (size, size), (255, 255, 255, 255))
        white.alpha_composite(rgba)
        return rgba, white.convert("RGB")

    def split_grid(grid_img: Image.Image):
        w, h = grid_img.size
        tiles = []
        if w >= h * 5:
            tw = w // 6
            for i in range(6):
                tiles.append(grid_img.crop((i * tw, 0, (i + 1) * tw, h)))
        elif abs((w / 3.0) - (h / 2.0)) < 16:
            tw, th = w // 3, h // 2
            for r in range(2):
                for c in range(3):
                    tiles.append(grid_img.crop((c * tw, r * th, (c + 1) * tw, (r + 1) * th)))
        elif abs((w / 2.0) - (h / 3.0)) < 16:
            tw, th = w // 2, h // 3
            for r in range(3):
                for c in range(2):
                    tiles.append(grid_img.crop((c * tw, r * th, (c + 1) * tw, (r + 1) * th)))
        else:
            raise ValueError(f"Unexpected MV-Adapter grid size: {w}x{h}")
        return tiles

    front_rgba, front_white = prepare_centered(front_src, 768)
    front_white_path = VIEWS_DIR / "front_white.png"
    front_white.save(front_white_path)
    front_rgba.save(VIEWS_DIR / "front.png")

    mv_raw_path = VIEWS_DIR / "mv_adapter_raw.png"
    prompt = spec.get(
        "prompt",
        "full body standing character, clean neutral background, 3D turnaround sheet, consistent proportions",
    )
    seed = int(spec.get("seed", 42))
    inf_script = MV_DIR / "scripts" / "inference_i2mv_sdxl.py"
    if inf_script.is_file():
        inf_txt = inf_script.read_text(encoding="utf-8")
        inf_txt = inf_txt.replace("pipe.enable_vae_slicing()", "pipe.vae.enable_slicing()")
        inf_txt = inf_txt.replace("pipe.enable_vae_tiling()", "pipe.vae.enable_tiling()")
        inf_script.write_text(inf_txt, encoding="utf-8")
    print("Pre-checking MV-Adapter imports ...", flush=True)
    subprocess.run(
        [sys.executable, "-c", "import mvadapter.utils.mesh_utils, mvadapter.utils.saving, scripts.inference_i2mv_sdxl; print('ALL MV-ADAPTER IMPORTS OK')"],
        cwd=str(MV_DIR),
        check=True,
    )
    print("Running MV-Adapter SDXL subprocess ...", flush=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.inference_i2mv_sdxl",
            "--image", str(front_white_path),
            "--text", prompt,
            "--seed", str(seed),
            "--output", str(mv_raw_path),
        ],
        cwd=str(MV_DIR),
        check=True,
    )

    tiles = split_grid(Image.open(mv_raw_path).convert("RGB"))
    view_imgs = {"front": front_rgba}
    for name, idx in (("right", 2), ("back", 3), ("left", 4)):
        rgba = rembg_remove(tiles[idx].convert("RGBA"))
        rgba.save(VIEWS_DIR / f"{name}.png")
        view_imgs[name] = rgba

    cell = 512
    grid = Image.new("RGB", (cell * 2, cell * 2), (242, 244, 248))
    draw = ImageDraw.Draw(grid)
    for name, (ox, oy) in (("front", (0, 0)), ("left", (cell, 0)), ("back", (0, cell)), ("right", (cell, cell))):
        im = view_imgs[name].copy()
        tile = Image.new("RGBA", (cell, cell), (245, 245, 248, 255))
        im.thumbnail((cell - 32, cell - 48), Image.Resampling.LANCZOS)
        tile.paste(im, ((cell - im.width) // 2, (cell - im.height) // 2 + 12), im)
        grid.paste(tile.convert("RGB"), (ox, oy))
        draw.rectangle([ox, oy, ox + cell - 1, oy + cell - 1], outline=(180, 190, 205), width=2)
        draw.text((ox + 14, oy + 10), name.upper(), fill=(25, 30, 40))
    grid.save(OUT_DIR / "views_grid.png")

    if str(HY_DIR) not in sys.path:
        sys.path.insert(0, str(HY_DIR))

    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline, FaceReducer, FloaterRemover
    try:
        from hy3dgen.shapegen import DegenerateFaceRemover
    except ImportError:
        DegenerateFaceRemover = None

    print("Loading Hunyuan3D-2mv shape pipeline ...", flush=True)
    shape_pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
        "tencent/Hunyuan3D-2mv",
        subfolder="hunyuan3d-dit-v2-mv",
        use_safetensors=True,
        device="cuda",
    )
    gen = torch.Generator(device="cuda").manual_seed(seed)
    mesh = shape_pipe(
        image=view_imgs,
        num_inference_steps=30,
        octree_resolution=380,
        num_chunks=20000,
        generator=gen,
        output_type="trimesh",
    )[0]
    mesh = FloaterRemover()(mesh)
    if DegenerateFaceRemover is not None:
        mesh = DegenerateFaceRemover()(mesh)
    mesh = FaceReducer()(mesh, max_facenum=int(spec.get("target_faces", 60000)))

    white_glb = OUT_DIR / "mesh_white.glb"
    mesh.export(str(white_glb))
    print("Exported white mesh:", white_glb, flush=True)
    with open(OUT_DIR / "manifest.json", "w", encoding="utf-8") as mf:
        json.dump({"files": ["views_grid.png", "mesh_white.glb"]}, mf, indent=2)

    del shape_pipe, mesh
    gc.collect()
    torch.cuda.empty_cache()

    from hy3dgen.texgen import Hunyuan3DPaintPipeline
    print("Loading Hunyuan3DPaintPipeline ...", flush=True)
    paint_pipe = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2")
    raw_mesh = trimesh.load(str(white_glb), force="mesh")
    textured_mesh = paint_pipe(raw_mesh, image=front_rgba)
    textured_glb = OUT_DIR / "mesh_textured.glb"
    textured_mesh.export(str(textured_glb))
    print("Exported textured mesh:", textured_glb, flush=True)

    generated = ["views_grid.png", "mesh_white.glb", "mesh_textured.glb"]
    with open(OUT_DIR / "manifest.json", "w", encoding="utf-8") as mf:
        json.dump({"files": generated}, mf, indent=2)

    del paint_pipe, textured_mesh
    gc.collect()
    torch.cuda.empty_cache()
    print("HUNYUAN3D JOB COMPLETED:", generated, flush=True)


if __name__ == "__main__":
    run_job()
'''


def _find_colab_bin() -> str:
    found = shutil.which("colab")
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / "colab"
    if candidate.is_file():
        return str(candidate)
    raise FileNotFoundError("colab CLI not found; install with `uv tool install --python 3.12 google-colab-cli`")


def _preflight_trellis2_hf_access(hf_token: str) -> None:
    """Verify HF Read Token has access to both gated TRELLIS.2 repos before booting a GPU VM."""
    tok = hf_token.strip()
    if not tok:
        raise RuntimeError(
            "TRELLIS.2 requires a Hugging Face Read token (--hf-token or HF_TOKEN env var) "
            "authorized on both `facebook/dinov3-vitl16-pretrain-lvd1689m` and `briaai/RMBG-2.0`."
        )
    curl_bin = shutil.which("curl")
    if not curl_bin:
        return
    denied: list[str] = []
    for repo, note in TRELLIS2_GATED_REPOS:
        url = f"https://huggingface.co/{repo}/resolve/main/config.json"
        res = subprocess.run(
            [curl_bin, "-s", "-o", "/dev/null", "-w", "%{http_code}", "-I", "-H", f"Authorization: Bearer {tok}", url],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        code = (res.stdout or "").strip()
        print(f"[HF Pre-flight] {repo} -> HTTP {code}", flush=True)
        if code not in ("200", "302"):
            denied.append(f"https://huggingface.co/{repo} (HTTP {code}, {note})")
    if denied:
        raise RuntimeError(
            "HF gated model pre-flight failed before booting Colab GPU. "
            "Accept the repository terms with your Hugging Face account first:\n  - " + "\n  - ".join(denied)
        )


def _colab_cmd(
    cmd: list[str],
    timeout: int = 90,
    retries: int = 6,
    input_text: str | None = None,
    capture: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a colab CLI command with hard timeout and automatic retry on transient network drops."""
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        print(f"$ {' '.join(cmd)} (attempt {attempt}/{retries}, timeout={timeout}s)", flush=True)
        try:
            proc = subprocess.run(
                cmd,
                input=input_text,
                text=True,
                timeout=timeout,
                capture_output=capture,
                check=check,
            )
            return proc
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            last_err = exc
            if capture and isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
                print(f"  [stderr] {exc.stderr.strip()[-400:]}", flush=True)
            if attempt < retries:
                wait_s = min(15, attempt * 4)
                print(f"  [WARN] Command failed ({type(exc).__name__}), retrying in {wait_s}s...", flush=True)
                time.sleep(wait_s)
    assert last_err is not None
    raise last_err


def _session_exists(colab_bin: str, session: str) -> bool:
    try:
        res = _colab_cmd([colab_bin, "sessions"], timeout=30, retries=5, capture=True, check=False)
        out = (res.stdout or "") + "\n" + (res.stderr or "")
        return f"[{session}]" in out
    except Exception:
        return False


def _launch_and_poll_remote(colab_bin: str, session: str, remote_bootstrap: str) -> None:
    launch_code = (
        "import os, subprocess, sys\n"
        "os.makedirs('/content/job_input', exist_ok=True)\n"
        "os.makedirs('/content/job_outputs', exist_ok=True)\n"
        "for p in ('/content/job.log', '/content/job_status.txt', '/content/job.pid'):\n"
        "    if os.path.exists(p): os.remove(p)\n"
        "log_f = open('/content/job.log', 'w', encoding='utf-8')\n"
        f"proc = subprocess.Popen([sys.executable, '-u', {remote_bootstrap!r}], "
        "stdout=log_f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)\n"
        "open('/content/job.pid', 'w').write(str(proc.pid))\n"
        "print('LAUNCHED_PID=' + str(proc.pid), flush=True)\n"
    )
    _colab_cmd([colab_bin, "exec", "-s", session, "--timeout", "45"], timeout=60, retries=6, input_text=launch_code)

    poll_template = (
        "import json, os\n"
        "offset = __OFFSET__\n"
        "log_path = '/content/job.log'\n"
        "chunk = ''\n"
        "new_offset = offset\n"
        "if os.path.exists(log_path):\n"
        "    size = os.path.getsize(log_path)\n"
        "    if size > offset:\n"
        "        with open(log_path, 'rb') as f:\n"
        "            f.seek(offset)\n"
        "            data = f.read(65536)\n"
        "        new_offset = offset + len(data)\n"
        "        chunk = data.decode('utf-8', errors='replace')\n"
        "status = open('/content/job_status.txt', 'r', encoding='utf-8').read() if os.path.exists('/content/job_status.txt') else ''\n"
        "pid_str = open('/content/job.pid').read().strip() if os.path.exists('/content/job.pid') else ''\n"
        "alive = bool(pid_str and os.path.exists('/proc/' + pid_str))\n"
        "print('===POLL_JSON===' + json.dumps({'offset': new_offset, 'status': status, 'alive': alive, 'chunk': chunk}), flush=True)\n"
    )

    offset = 0
    consecutive_errors = 0
    start_ts = time.monotonic()
    while True:
        time.sleep(20)
        try:
            res = subprocess.run(
                [colab_bin, "exec", "-s", session, "--timeout", "35"],
                input=poll_template.replace("__OFFSET__", str(offset)),
                text=True,
                timeout=50,
                capture_output=True,
                check=True,
            )
            consecutive_errors = 0
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
            consecutive_errors += 1
            print(f"  [WARN] Log poll transient error ({consecutive_errors}/8): {type(exc).__name__}", flush=True)
            if consecutive_errors >= 8:
                raise RuntimeError("Aborted after 8 consecutive log polling failures.") from exc
            continue

        marker = "===POLL_JSON==="
        payload = None
        for line in (res.stdout or "").splitlines():
            if marker in line:
                payload = json.loads(line.split(marker, 1)[1])
                break
        if payload is None:
            continue

        offset = int(payload.get("offset", offset))
        chunk = payload.get("chunk") or ""
        if chunk:
            print(chunk, end="" if chunk.endswith("\n") else "\n", flush=True)

        status = (payload.get("status") or "").strip()
        alive = bool(payload.get("alive"))
        elapsed_min = (time.monotonic() - start_ts) / 60.0
        if status.startswith("DONE"):
            print(f"[DONE] Remote job completed in {elapsed_min:.1f} min.", flush=True)
            return
        if status.startswith("ERROR"):
            raise RuntimeError(f"Remote job failed:\n{status}")
        if not alive and elapsed_min > 0.5:
            raise RuntimeError("Remote background process exited without writing DONE status.")


def run_one_engine(
    colab_bin: str,
    engine: str,
    input_img: Path,
    gpu: str,
    spec: dict,
    local_asset_out: Path,
    drive_asset_out: Path | None,
    keep: bool,
) -> list[Path]:
    session = f"kit-{engine}"
    remote_code = REMOTE_TRELLIS2_CODE if engine == "trellis2" else REMOTE_HUNYUAN3D_CODE
    remote_inner_script = f"/content/run_{engine}_inner.py"
    remote_bootstrap_script = f"/content/run_{engine}_bootstrap.py"
    ext = input_img.suffix.lower() or ".png"
    downloaded: list[Path] = []

    with tempfile.TemporaryDirectory(prefix=f"kit_{engine}_") as tmp:
        tmp_dir = Path(tmp)
        spec_path = tmp_dir / "job_spec.json"
        inner_path = tmp_dir / f"run_{engine}_inner.py"
        bootstrap_path = tmp_dir / f"run_{engine}_bootstrap.py"
        manifest_local = tmp_dir / "manifest.json"
        spec_path.write_text(json.dumps(spec, indent=2, ensure_ascii=False), encoding="utf-8")
        inner_path.write_text(remote_code, encoding="utf-8")
        bootstrap_path.write_text(
            REMOTE_BOOTSTRAP_CODE.replace("__INNER_SCRIPT__", remote_inner_script),
            encoding="utf-8",
        )

        if _session_exists(colab_bin, session):
            print(f"[REUSE] Reusing existing Colab session {session} ...", flush=True)
        else:
            _colab_cmd([colab_bin, "new", "-s", session, "--gpu", gpu], timeout=120, retries=6)

        try:
            _colab_cmd(
                [colab_bin, "exec", "-s", session, "--timeout", "45"],
                timeout=60,
                retries=6,
                input_text="import os; os.makedirs('/content/job_input', exist_ok=True); os.makedirs('/content/job_outputs', exist_ok=True)\n",
            )
            _colab_cmd([colab_bin, "upload", "-s", session, str(spec_path), "/content/job_spec.json"], timeout=60, retries=6)
            _colab_cmd([colab_bin, "upload", "-s", session, str(inner_path), remote_inner_script], timeout=60, retries=6)
            _colab_cmd([colab_bin, "upload", "-s", session, str(bootstrap_path), remote_bootstrap_script], timeout=60, retries=6)
            _colab_cmd([colab_bin, "upload", "-s", session, str(input_img), f"/content/job_input/front{ext}"], timeout=90, retries=6)

            _launch_and_poll_remote(colab_bin, session, remote_bootstrap_script)

            _colab_cmd(
                [colab_bin, "download", "-s", session, "/content/job_outputs/manifest.json", str(manifest_local)],
                timeout=60,
                retries=6,
            )
            manifest = json.loads(manifest_local.read_text(encoding="utf-8"))
            for rel in manifest.get("files") or []:
                fname = Path(rel).name
                dst = local_asset_out / fname
                _colab_cmd(
                    [colab_bin, "download", "-s", session, f"/content/job_outputs/{rel}", str(dst)],
                    timeout=180,
                    retries=6,
                )
                downloaded.append(dst)
                if drive_asset_out is not None:
                    drive_asset_out.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(dst, drive_asset_out / fname)
        finally:
            if not keep:
                print(f"[STOP] Stopping Colab session {session} to release GPU ...", flush=True)
                try:
                    _colab_cmd([colab_bin, "stop", "-s", session], timeout=60, retries=5, check=False)
                except Exception as stop_exc:
                    print(f"[WARN] Failed to stop session (verify `colab usage` = 0.00/hr): {stop_exc}", flush=True)

    return downloaded


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run TRELLIS.2-4B and/or Hunyuan3D-2mv headlessly on Colab L4 via google-colab-cli."
    )
    parser.add_argument("--engine", choices=("trellis2", "hunyuan3d", "both"), default="trellis2")
    parser.add_argument("--input", type=Path, required=True, help="Front-view 2D character/object image")
    parser.add_argument("--name", required=True, help="Output asset subdirectory name")
    parser.add_argument("--gpu", default="L4", help="Colab GPU type (default: L4)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-faces", type=int, default=60000)
    parser.add_argument("--texture-size", type=int, default=2048)
    parser.add_argument("--prompt", default="", help="Optional MV-Adapter prompt override for hunyuan3d")
    parser.add_argument("--out-dir", type=Path, default=KIT_ROOT / "workspace" / "outputs_3d")
    parser.add_argument(
        "--hf-token",
        default=os.environ.get("HF_TOKEN", ""),
        help="Hugging Face Read token (required for TRELLIS.2 gated repos: dinov3 & RMBG-2.0)",
    )
    parser.add_argument("--skip-preflight", action="store_true", help="Skip 1s HF gated-repo curl check")
    parser.add_argument("--keep", action="store_true", help="Keep Colab VM alive after completion (default: stop)")
    args = parser.parse_args()

    input_img = args.input.expanduser().resolve()
    if not input_img.is_file():
        raise FileNotFoundError(f"Input image not found: {input_img}")

    engines = ("hunyuan3d", "trellis2") if args.engine == "both" else (args.engine,)
    if "trellis2" in engines and not args.skip_preflight:
        _preflight_trellis2_hf_access(args.hf_token)

    colab_bin = _find_colab_bin()
    local_asset_out = args.out_dir.expanduser().resolve() / args.name
    local_asset_out.mkdir(parents=True, exist_ok=True)

    drive_asset_out: Path | None = None
    cfg = load_config()
    drive_root = find_google_drive_my_drive(config=cfg)
    if drive_root and drive_root.exists():
        drive_asset_out = get_studio_dir(drive_root, cfg) / "outputs_3d" / args.name
        drive_asset_out.mkdir(parents=True, exist_ok=True)

    spec: dict[str, object] = {
        "name": args.name,
        "seed": args.seed,
        "target_faces": args.target_faces,
        "texture_size": args.texture_size,
        "hf_token": args.hf_token,
    }
    if args.prompt.strip():
        spec["prompt"] = args.prompt.strip()

    results: dict[str, dict] = {}
    for eng in engines:
        print(f"\n========== Running 3D engine: {eng} ({args.name}) ==========", flush=True)
        try:
            outs = run_one_engine(
                colab_bin=colab_bin,
                engine=eng,
                input_img=input_img,
                gpu=args.gpu,
                spec=spec,
                local_asset_out=local_asset_out,
                drive_asset_out=drive_asset_out,
                keep=args.keep,
            )
            results[eng] = {"ok": True, "files": outs, "error": None}
            print(f"========== Finished {eng}: {len(outs)} file(s) ==========\n", flush=True)
        except Exception as exc:
            results[eng] = {"ok": False, "files": [], "error": str(exc)}
            print(f"[ERROR] Engine {eng} failed: {exc}\n", flush=True)

    print("========== Summary ==========", flush=True)
    any_fail = False
    for eng in engines:
        st = results[eng]
        if st["ok"]:
            print(f"[OK] {eng}: {len(st['files'])} file(s)", flush=True)
            for p in st["files"]:
                print(f"   - {p} ({p.stat().st_size / (1024**2):.2f} MB)", flush=True)
        else:
            any_fail = True
            print(f"[FAIL] {eng}: {st['error']}", flush=True)

    if drive_asset_out:
        print(f"Google Drive mirror: {drive_asset_out}", flush=True)
    return 1 if any_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
