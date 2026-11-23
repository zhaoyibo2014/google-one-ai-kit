# 常见踩坑与故障排查手册

本手册收录了真实复刻 **Google Drive Desktop + Colab + ComfyUI + ai-toolkit** 全流程时验证过的高频坑与标准解法。

---

## 1. Colab「Open notebook -> Google Drive」显示 `No results`

- **现象**：本地脚本明明把 `.ipynb` 同步进了 Google Drive，但 Colab 打开对话框搜不到任何文件。
- **原因**：刚通过 Google Drive 桌面版上传的 `.ipynb`，Colab 的文件索引会有延迟，且有时未标记为 Colaboratory 关联类型。
- **解法**：不要用搜索框，直接运行本仓库脚本读取文件扩展属性里的 Drive File ID 生成直达链接：
  ```bash
  .venv/bin/python scripts/get_colab_urls.py
  ```
  直接点击输出的 `https://colab.research.google.com/drive/<FILE_ID>` 即可秒开（打开一次后即会出现在 Recent 列表）。

---

## 2. `drive.mount('/content/drive')` 报错 `Error: credential propagation was unsuccessful`

- **原因**：
  1. 在某些 IDE 内嵌简易浏览器中运行 Colab，OAuth 弹窗回传被拦截；或
  2. 授权弹窗里**漏勾了云端硬盘读写权限复选框**。
- **解法**：
  1. 改用完整的 **Google Chrome**（或内置支持完整 OAuth 的浏览器）打开 Colab；
  2. 授权弹窗出现时，务必勾选 **Select all / 查看、修改、创建和删除 Google 云端硬盘文件**，再点 Continue；
  3. 若仍失败，点 Colab 左侧栏 📁 图标 -> 点击顶部 **Mount Drive** 按钮手动挂载一次。

---

## 3. 在 Colab 下载 16 GB 模型显示成功，但关机后云盘里变成 `0 B` 或文件消失

- **现象**：`00_setup_and_download_models.ipynb` 打印模型下载完成，但直接断开连接后，Mac 访达里只看到部分小文件或文件大小为 `0 B`。
- **原因**：Colab 的 `/content/drive` 基于 FUSE 异步缓存写入，十几 GB 的大文件在 Python 返回时可能还在虚拟机缓存队列里慢慢往 Google Drive 服务端上传。
- **解法**：下载完成后**必须执行 `drive.flush_and_unmount()`**，等待它打印成功后再断开运行时（`00_setup_and_download_models.ipynb` 的第 5 步和 `02_train_style_lora.ipynb` 的第 5 步已内置此强制刷盘步骤）。

---

## 4. macOS 中文系统下找不到 `My Drive`

- **现象**：简体中文 macOS 下 Google Drive 挂载路径叫 `我的云端硬盘`，繁体叫 `我的雲端硬碟`，英文叫 `My Drive`。
- **解法**：`scripts/common.py` 已内置多语言探测，自动依次检查：
  `~/Library/CloudStorage/GoogleDrive-*/{My Drive, 我的云端硬盘, 我的雲端硬碟}`、`/Volumes/GoogleDrive/...` 以及 Windows `D:`~`Z:` 盘符。

---

## 5. Cloudflare Tunnel 链接打开报 `ERR_CONNECTION_TIMED_OUT` 或 502

- **原因**：`cloudflared` 比 ComfyUI 主进程启动快，ComfyUI 还没监听 `8188` 端口就对外暴露了隧道。
- **解法**：`01_comfyui_studio.ipynb` 第 4 步已改为先循环轮询 `http://127.0.0.1:8188/system_stats` 直到返回 HTTP `200`，再启动 `cloudflared` 并打印隧道 URL。若依然打不开，检查 `/content/comfyui.log` 末尾日志，或确保保持 Colab 页面开启（Colab 断连会立刻切断隧道）。

---

## 6. macOS Python `urllib` 报 `SSL: CERTIFICATE_VERIFY_FAILED`

- **现象**：某些 macOS 官方 Python.org 安装包未执行 `Install Certificates.command`，直接用 `urllib.request` 请求 HTTPS 会报证书校验失败。
- **解法**：`scripts/install_google_drive.py` 统一调用系统自带 `curl -fSL` 下载官方安装包；若自写脚本用 `pip` 或 `requests` 遇证书问题，可配置 `SSL_CERT_FILE=$(python3 -c 'import certifi; print(certifi.where())')`。

---

## 7. 训练 LoRA 时 Colab 报 `401 / 403` 无法拉取 `black-forest-labs/FLUX.1-dev`

- **原因**：`Comfy-Org/Flux-1-Dev`（用于 ComfyUI 推理）免登录免协议，但 `ostris/ai-toolkit` 训练脚本默认拉取官方 `black-forest-labs/FLUX.1-dev`（Gated 仓库）。
- **解法**：
  1. 浏览器登录 Hugging Face，打开 `https://huggingface.co/black-forest-labs/FLUX.1-dev` 点击 **Agree**；
  2. 在 Hugging Face Settings -> Access Tokens 创建 **Read** Token；
  3. 在 Colab 左侧栏 🔑 **Secrets** 添加 `HF_TOKEN` 并打开 **Notebook access** 开关。

---

## 8. 安装 `google-colab-cli` 报错 `Requires-Python >= 3.12`

- **现象**：macOS 系统 Python 3.11 下直接 `pip install google-colab-cli` 找不到可用版本。
- **解法**：不要强改现有 `.venv`，直接用 `uv` 独立托管安装：
  ```bash
  brew install uv
  uv tool install --python 3.12 google-colab-cli
  ```
  安装后可通过 `~/.local/bin/colab usage` 完成一次性 OAuth 并永久写入系统钥匙串。

---

## 9. `colab exec` 执行生图/拉模中途 30 秒超时中断

- **原因**：`google-colab-cli` 的 `colab exec` 默认 `--timeout` 为 `30.0` 秒（无标准输出超过 30 秒即判失败），而模型加载或单张扩散采样经常超过 30 秒。
- **解法**：调用长耗时脚本时务必加上 **`--timeout 0`**（`scripts/colab_cli_flux.py` 已默认配置 `--timeout 0` 并开启 `flush=True` 实时回显）；对于需要编译 CUDA 扩展的 20~30 分钟任务，改用 `scripts/colab_cli_3d.py` 的「后台脱离进程 + 20 秒增量轮询日志 + 重试」机制防止网络瞬断挂死。

---

## 10. Colab 默认 Python 3.13 + CUDA 13.0 导致 3D CUDA 扩展编译全挂

- **现象**：在 Colab 宿主机环境直接编译 `nvdiffrast`、`cumesh`、`o_voxel`、`custom_rasterizer` 时报 C++ / NVCC / PyTorch ABI 不兼容。
- **解法**：在 VM 内通过 `micromamba` 拉起隔离环境 `/opt/mamba3d`（`python=3.11` + `cuda-toolkit=12.4.1` + `gcc_linux-64=12` + `torch==2.6.0+cu124`），并设 `TORCH_CUDA_ARCH_LIST=8.9`、`MAX_JOBS=4` 与 `MPLBACKEND=Agg`。详见 [2D 转 3D 实战手册](./image-to-3d-colab.md)。

---

## 11. `transformers 5.x` 破坏 `Hunyuan3D-2mv` 与 `TRELLIS.2` 视觉编码器

- **现象**：
  - `Hunyuan3D-2mv` 报 `SingleImageEncoder`（`DINOv2`）层键名不匹配；
  - `TRELLIS.2` 报 `AttributeError: 'DINOv3ViTModel' object has no attribute 'layer'`。
- **解法**：`Hunyuan3D-2mv` 锁定 `transformers==4.46.3`、`diffusers==0.31.0`、`huggingface_hub<1.0.0`；`TRELLIS.2` 锁定 `transformers==4.57.6`、`huggingface-hub>=0.34.0,<1.0.0`、`tokenizers>=0.22.0,<=0.23.0` 并加 `DINOV3_LAYER_OK` 预检。

---

## 12. 跑 `TRELLIS.2` 报 `403`：`briaai/RMBG-2.0` 与 `DINOv3` 双门控缺失

- **现象**：只放行了 `facebook/dinov3-vitl16-pretrain-lvd1689m`，进到 `Trellis2ImageTo3DPipeline.from_pretrained` 时被第二个隐藏门控仓库 `briaai/RMBG-2.0` 拦截。
- **解法**：`DINOv3` 需人工审批（1~2 天），`RMBG-2.0` 点 **Agree** 即自动秒批。运行 `scripts/colab_cli_3d.py` 时会自动先用 `curl` 1 秒预检两个仓库均返回 `HTTP 200` 再开 GPU 卡。

---

## 13. `TRELLIS.2` 报 `No module named 'flash_attn'` 或 C++11 ABI 符号未定义

- **现象**：`trellis2/modules/sparse/config.py` 忽略 `SPARSE_ATTN_BACKEND=sdpa` 并回退到 `flash_attn`；若强装第三方 `flash_attn` 预编译 wheel 容易报 `_ZN3c105ErrorC2...` 符号错配，源码编译则耗时 30+ 分钟。
- **解法**：设 `ATTN_BACKEND=sdpa` + **`SPARSE_ATTN_BACKEND=xformers`**，安装与 `torch==2.6.0` 原生匹配的官方 **`xformers==0.0.29.post3 --no-deps`**（~5 秒免编译），并在推理前跑 `XFORMERS_CUDA_OK` 算子自检。

---

## 14. `Hunyuan3DPaint` 找不到 `custom_rasterizer` 或 `libc10.so`

- **现象**：用 `pip install -e .` 安装 `custom_rasterizer` / `differentiable_renderer` 后导入失败，或加载 `.so` 时缺 `torch/lib` 动态库路径。
- **解法**：改用非可编辑正式安装（`pip install . --no-build-isolation --no-deps`），把 `site-packages/torch/lib` 注入 `LD_LIBRARY_PATH`，并在流程前做 `CUSTOM_RASTERIZER_OK` 导入预检。

---

## 15. `TRELLIS.2` 转盘预览 `cv2.imread("forest.exr")` 返回 `None` 导致崩溃

- **现象**：新版 OpenCV 5.1.0 默认无法读取 `.exr`，在导出 `.glb` 前执行 `cv2.cvtColor(hdri_bgr, ...)` 直接抛 `Assertion failed: !_src.empty()` 退出。
- **解法**：`scripts/colab_cli_3d.py` 已将 `trellis2_pbr.glb` 导出提前至预览渲染之前，并在读取 `.exr` 失败时自动回退到程序化柔光 `EnvMap` 张量。
