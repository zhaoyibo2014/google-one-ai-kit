---
name: google-one-ai-kit
description: >-
  Orchestrate the full Google One / Google AI Pro ecosystem end-to-end: mount 5 TB Google Drive
  in zero-disk-footprint stream mode, auto-download Google Drive Desktop, cache 19 GB FLUX.1-dev FP8
  + Redux models on FREE Colab CPU (0 compute units burned), launch ComfyUI via Cloudflare Tunnel on
  Colab L4 GPU, run headless 2D-to-3D PBR mesh generation (`TRELLIS.2-4B` & `Hunyuan3D-2mv`) via
  `google-colab-cli`, train custom style LoRAs with ostris/ai-toolkit, and maximize monthly
  developer/creative perks ($10 Cloud/Gemini API credits, Whisk, Flow, Antigravity, Jules, NotebookLM).
  Use whenever a user wants to set up Colab + Google Drive for AI image generation, run headless
  2D-to-3D on Colab L4, replicate a Google AI Pro studio workflow, train a custom FLUX style LoRA on
  Colab, or avoid wasting Google One AI Pro benefits.
---

# Google One AI Kit — Agent-First Automation Playbook

**Core Principle: The user only performs one-time logins/OAuth approvals (or optional installer drag-and-drop). The Agent automates environment checks, installer downloads, `.venv` setup, Drive syncing, headless Colab CLI provisioning & generation, browser fallback, smoke testing, and runtime shutdown.**

---

## Execution Mode Selection

- **Mode A (Recommended on macOS / Linux): CLI Automation (`google-colab-cli`)**
  - Best for batch generation, multi-reference Redux style mixing, and zero-babysitting execution: **0 browser windows**, **0 repeated Google Drive OAuth popups**, one-time login cached in OS Keyring, and automatic `colab stop` on exit.
  - Install `google-colab-cli` (requires Python >= 3.12; use `uv` so the local 3.11 `.venv` stays untouched):
    ```bash
    # macOS: brew install uv (or: pip install uv)
    uv tool install --python 3.12 google-colab-cli
    ```
  - **One-time OAuth**: Run `colab usage` (use `~/.local/bin/colab` if not yet on `PATH`). When it prints the `https://accounts.google.com/o/oauth2/...` URL and waits at `Enter the authorization code:`, show the URL to the user, ask them to paste back the authorization code, and pipe it into the waiting process (`send_input`). The refresh token is saved in the OS Keyring for all future sessions.
  - **CLI-Automated FLUX / Multi-Redux generation** (provisions L4, clones ComfyUI + downloads ungated models on Colab datacenter network, queues API jobs, downloads PNGs locally + mirrors to Drive `outputs/`, and runs `colab stop` in `finally:`):
    ```bash
    .venv/bin/python scripts/colab_cli_flux.py \
      --gpu L4 \
      --ref workspace/style_refs/ref_style_01.png:0.42 \
      --prompt "mystyle, ..." \
      --prefix studio_gen \
      --count 2
    ```
    - Pass `--ref` multiple times to blend 2+ style anchors in one graph, or pass `--job-json <path>` to run multiple prompts/strengths in a single L4 session.
    - Always verify `colab sessions` / `colab usage` shows `Active assignments: 0` afterward.
  - **CLI-Automated 2D-to-3D PBR Mesh Generation (`TRELLIS.2-4B` & `Hunyuan3D-2mv`)**:
    - Provisions an isolated `/opt/mamba3d` environment (Python 3.11 + CUDA 12.4.1 + GCC 12 + PyTorch 2.6.0+cu124) inside Colab L4 so CUDA extensions (`o_voxel`, `cumesh`, `flex_gemm`, `nvdiffrast`, `custom_rasterizer`) compile cleanly even on Colab's Python 3.13 / CUDA 13.0 image, using detached background execution + incremental `/content/job.log` polling + automatic `colab stop`.
    - **Mandatory 1-second HF pre-flight for `TRELLIS.2-4B`**: `TRELLIS.2` depends on **two** gated Hugging Face repos (`facebook/dinov3-vitl16-pretrain-lvd1689m` manual approval + `briaai/RMBG-2.0` auto-approve upon clicking Agree). `scripts/colab_cli_3d.py` automatically checks both with `curl -I` before booting a paid L4 VM.
      ```bash
      # Recommended: Microsoft TRELLIS.2-4B (full PBR baseColor + metallicRoughness GLB)
      HF_TOKEN="hf_..." .venv/bin/python -u scripts/colab_cli_3d.py \
        --engine trellis2 --input path/to/front_apose.png --name hero_v1 --gpu L4

      # Alternative / No-HF-Gate: Tencent MV-Adapter + Hunyuan3D-2mv + Hunyuan3DPaint
      .venv/bin/python -u scripts/colab_cli_3d.py \
        --engine hunyuan3d --input path/to/front_apose.png --name hero_v1 --gpu L4
      ```
    - Read [references/image-to-3d-colab.md](./references/image-to-3d-colab.md) for benchmark comparisons, 2D prep rules, and all 10 verified Colab 3D pitfalls.
    - Always verify `~/.local/bin/colab usage` shows `Usage rate: 0.00/hr` and `Active assignments: 0` after completion or failure.
- **Mode B (Windows or Interactive Node Tweaking): Browser + Google Drive Notebooks**
  - Use Phases 1–3 below when running on Windows (not yet supported by `google-colab-cli`) or when the user wants interactive ComfyUI web UI access.

---

## Phase 0: Local Probe & Auto-Install Google Drive Desktop

1. **Create `.venv` if missing and probe the machine**:
   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python scripts/check_env.py
   ```
2. **If Google Drive Desktop is NOT mounted**:
   - Run the automatic installer downloader:
     ```bash
     .venv/bin/python scripts/install_google_drive.py
     ```
   - This downloads the official installer (`GoogleDrive.dmg` on macOS / `GoogleDriveSetup.exe` on Windows) into `~/Downloads` and opens it automatically.
   - **Tell the user the exact 2 clicks to avoid filling local SSD**:
     1. Sign in with the Google One / Google AI Pro account.
     2. On **"Choose folders to sync from your computer"**, uncheck everything and click **`Skip`**.
     3. On **"See Drive files in Finder / Explorer"**, click **`Next`** (keep default **Stream files** mode so 19 GB cloud models never consume local SSD).
   - Once the user finishes the wizard, re-run `.venv/bin/python scripts/check_env.py` to confirm `My Drive` / `我的云端硬盘` is mounted.

---

## Phase 1: Sync Studio Files & Extract Direct Colab URLs

1. If the user provides style reference images, place them in `workspace/style_refs/` (or configure `config.local.yaml` copied from `config.example.yaml`).
2. Sync notebooks, ComfyUI workflows, and reference images to `GoogleOneAI_Studio/`:
   ```bash
   .venv/bin/python scripts/sync_to_drive.py
   ```
3. **Never rely on Colab's `Open notebook -> Google Drive` search dialog for newly uploaded `.ipynb` files** (newly synced desktop files may show `No results` before indexing). Instead, extract the exact Drive File ID URLs immediately:
   ```bash
   .venv/bin/python scripts/get_colab_urls.py --json
   ```
   - If `status == "pending_upload"`, wait 10–15 seconds for Drive Desktop background upload to finish and retry `get_colab_urls.py`.

---

## Phase 2: Cache 19 GB FLUX Models on FREE Colab CPU (0 Compute Units)

Launch the browser agent on the `00_setup_and_download_models.ipynb` direct Colab URL from Phase 1:

1. **Verify Runtime = `CPU`**: Open `Runtime -> Change runtime type` and ensure **`CPU`** is selected (never GPU — downloading models wastes compute units if GPU is attached).
2. Click **`Run all`**.
3. **Pause ONLY for Google Drive OAuth**: When Colab asks *"Permit this notebook to access your Google Drive files?"*, tell the user to click **`Connect to Google Drive`**, select their Google account, **check all Drive permission checkboxes (`Select all`)**, and click **Continue**.
4. Wait until **Cell 4** verifies all 3 ungated models (`flux1-dev-fp8.safetensors` ~16.06 GB, `flux1-redux-dev.safetensors` ~0.12 GB, `sigclip_vision_patch14_384.safetensors` ~0.80 GB) AND **Cell 5** finishes `drive.flush_and_unmount()` (prevents large FUSE-cached files from vanishing after disconnect!).
5. Confirm locally via `.venv/bin/python scripts/check_env.py` that the files exist in Drive, then click **`Runtime -> Disconnect and delete runtime`**.

---

## Phase 3: Launch ComfyUI on Colab L4 GPU & Smoke-Test

Open the `01_comfyui_studio.ipynb` direct Colab URL in the browser agent:

1. Switch runtime: `Runtime -> Change runtime type -> L4 GPU` (24 GB VRAM, ~1.7 compute units/hr) -> `Save`.
2. Click **`Run all`** (pause only for the Google Drive OAuth dialog if prompted).
3. Cell 4 clones ComfyUI + Manager, maps `extra_model_paths.yaml` directly to Drive (zero copy), waits for `http://127.0.0.1:8188/system_stats` HTTP 200, and prints a public `https://*.trycloudflare.com` URL.
4. Open that URL in a new tab (keep the Colab tab open so the tunnel stays alive), load `01_flux_base_lora.json` (or `02_flux_redux_style.json` if reference images were synced), and queue 1 test image (`Batch Count = 1`).
5. Verify the generated `.png` appears locally inside Drive `GoogleOneAI_Studio/outputs/`.

---

## Phase 4: Style Locking -> Curated Dataset -> Custom LoRA Training

1. **Collect 15–25 cohesive style anchors** using `02_flux_redux_style.json`:
   - Set `StyleModelApply.strength` to **`0.35 ~ 0.50`** to lock color palette, lighting, and rendering style while letting text prompts vary subjects/poses (`0.65 ~ 0.85` yields tighter visual variations).
2. **Prepare the LoRA dataset locally** (place 15–25 best outputs into `workspace/raw_selected/`):
   ```bash
   .venv/bin/python scripts/prep_lora_dataset.py --input workspace/raw_selected --sync-to-drive
   ```
   - Inspect and refine the generated `.txt` captions (keep the leading trigger word, e.g. `mystyle, ...`, and accurately describe subject, outfit, pose, and background), then re-run `sync_to_drive.py --include-dataset`.
3. **Train the LoRA** via `02_train_style_lora.ipynb` (`L4` or `A100` GPU):
   - User prerequisite: accept the license on `black-forest-labs/FLUX.1-dev` on Hugging Face and add a Read `HF_TOKEN` to Colab **Secrets** (key icon on left sidebar) with **Notebook access** enabled.
   - Run all cells; `ostris/ai-toolkit` automatically applies `quantize + low_vram` on 24 GB L4, trains the LoRA, copies `<RUN_NAME>.safetensors` into `GoogleOneAI_Studio/models/loras/`, and calls `drive.flush_and_unmount()`.
   - Next time ComfyUI starts, select `LoraLoader` in `01_flux_base_lora.json` and press `Ctrl+B` to un-bypass and generate pure text-to-image in your custom style.

---

## Phase 5: Mandatory Cost-Control & Full Perks Utilization

- **Always shut down GPU runtimes when idle**: Stop Cell 4, then click **`Runtime -> Disconnect and delete runtime`**, and confirm `Runtime -> Manage sessions` shows **0 active sessions**. Leaving an idle L4 tab open continuously drains monthly compute units.
- **Maximize the rest of the Google One AI Pro suite**: Read [references/google-ai-pro-perks.md](./references/google-ai-pro-perks.md) to guide the user on activating their **\$10/mo Google Cloud / Gemini API credits**, **1,000 monthly Flow credits**, **Whisk style mixing**, **Antigravity / Jules**, and **NotebookLM**.
- **If any step fails**: Check [references/troubleshooting.md](./references/troubleshooting.md) first.
