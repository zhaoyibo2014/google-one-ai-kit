# Colab L4 无头 2D 转 3D（TRELLIS.2 & Hunyuan3D-2mv）实战手册

> 本手册沉淀了在 Google Colab L4（24 GB 显存）上通过 `google-colab-cli` 无头安装并跑通 **Microsoft `TRELLIS.2-4B`** 与 **Tencent `Hunyuan3D-2mv`（`MV-Adapter` + `Hunyuan3D-2mv` + `Hunyuan3DPaint`）** 的完整制作流程、实测对比与全部避坑方案。

---

## 1. 为什么用 Colab L4 无头跑 2D → 3D？

- **本地痛点**：Mac M 系列统一内存或普通轻薄本缺少 NVIDIA CUDA 环境，无法编译 `o_voxel`、`cumesh`、`flex_gemm`、`nvdiffrast`、`custom_rasterizer` 等底层光栅化/稀疏卷积扩展。
- **Colab L4 实测表现**：
  - 全冷启动（拉起隔离 Python 3.11 + CUDA 12.4.1 环境、编译全部 CUDA 扩展、下载权重、推理并回传 `.glb`）：
    - `Hunyuan3D-2mv`：约 **21 分钟**，消耗约 **0.60 compute units**；
    - `TRELLIS.2-4B`：约 **27 分钟**，消耗约 **0.84 compute units**；
  - 用 `scripts/colab_cli_3d.py` 无头调度，跑完 `finally:` 自动执行 `colab stop`，**0 浏览器常驻、0 闲置扣费**。

---

## 2. 双引擎实测对比与选型建议

基于同一张二次元全身立绘（`60,000` 目标面数、`2048` 贴图分辨率）在 Colab L4 上的实测对比：

| 维度 | Microsoft `TRELLIS.2-4B`（`trellis2_pbr.glb`） | Tencent `Hunyuan3D-2mv`（`mesh_textured.glb`） |
| :--- | :--- | :--- |
| 产物清单 | `trellis2_pbr.glb`、`trellis2_preview.mp4`、`trellis2_preview_grid.png` | `views_grid.png`、`mesh_white.glb`、`mesh_textured.glb` |
| 文件体积 / 拓扑 | ~`11.4 MB`（`48,909` 顶点 / `57,679` 三角面） | ~`4.1 MB`（`39,099` 顶点 / `60,000` 三角面） |
| 包围盒比例 | X:Y:Z ≈ `0.43 : 1.00 : 0.27`（人体纵横比自然） | 侧向 Z 轴易受多视图脑补影响偏宽 |
| PBR 贴图通道 | **完整 PBR**：`baseColorTexture` + `metallicRoughnessTexture`（金属甲胄/刀刃与布料/皮肤高光分离清晰） | 仅 `baseColorTexture`（无金属度/粗糙度贴图） |
| 武器与细长结构 | 侧向长剑/法杖保持笔直纤细，不易膨胀 | 依赖 `MV-Adapter` 生成的四视图，侧面细剑可能被脑补变宽 |
| Hugging Face 门控 | 需提前放行 **2 个门控仓库** + 传 `HF_TOKEN` | **免 Token / 无需门控审批**，开箱即用 |
| **选型建议** | **主力首选**（尤其适合带 PBR 材质的游戏引擎落地） | 备选或需要四视图先控形再重建时使用 |

---

## 3. 前置准备（2 分钟）

### 3.1 输入 2D 原画准备规范（决定 3D 成败的 70%）

- **姿态**：正面直立 **A-pose**（手臂微张离开躯干 20°~30°，双腿微分开），避免抱胸、坐姿或大幅透视动作；
- **道具与衣摆**：武器/披风尽量与躯干、腿部**零重叠分离**（如果原画武器挡住身体，可先用 Gemini / Flux 修成单手侧持且与衣摆留白分离）；
- **背景**：纯色干净背景（白底或浅灰底最佳）。

### 3.2 `TRELLIS.2` 双门控仓库 1 秒预检（务必在开卡前做！）

`microsoft/TRELLIS.2-4B` 的 `pipeline.json` 实际上依赖 **两个** Hugging Face 门控仓库，缺一不可：

1. [`facebook/dinov3-vitl16-pretrain-lvd1689m`](https://huggingface.co/facebook/dinov3-vitl16-pretrain-lvd1689m) — **人工审批（`manual`）**，提交申请后通常需等待 Meta 审核 1~2 天；
2. [`briaai/RMBG-2.0`](https://huggingface.co/briaai/RMBG-2.0) — **自动秒批（`auto`）**，登录后打开页面点一下 **Agree and access repository** 立即生效。

在 Hugging Face Settings → Access Tokens 创建一个 **Read** 权限 Token，在本地终端跑一次 **1 秒 `curl` 预检**（不要浪费 GPU 点数在 403 上）：

```bash
export HF_TOKEN="hf_你的ReadToken"
for repo in facebook/dinov3-vitl16-pretrain-lvd1689m briaai/RMBG-2.0; do
  code=$(curl -s -o /dev/null -w "%{http_code}" -I \
    -H "Authorization: Bearer $HF_TOKEN" \
    "https://huggingface.co/$repo/resolve/main/config.json")
  echo "$repo -> HTTP $code"
done
```

必须两个都返回 **`HTTP 200`** 再启动 Colab GPU（`scripts/colab_cli_3d.py` 已内置该预检，未放行会在建机前直接报错退出）。

---

## 4. 一键无头跑模流程

确保已按 `SKILL.md` 完成 `google-colab-cli` 安装与一次性 OAuth 登录（`~/.local/bin/colab usage` 可正常显示余额）：

### 跑 `TRELLIS.2-4B`（推荐主选）

```bash
HF_TOKEN="hf_你的ReadToken" .venv/bin/python -u scripts/colab_cli_3d.py \
  --engine trellis2 \
  --input /path/to/front_character.png \
  --name hero_v1 \
  --gpu L4
```

### 跑 `Hunyuan3D-2mv`（免 HF 门控，或同时跑双引擎对比 `--engine both`）

```bash
.venv/bin/python -u scripts/colab_cli_3d.py \
  --engine hunyuan3d \
  --input /path/to/front_character.png \
  --name hero_v1 \
  --gpu L4
```

产物会自动拉回本地 `workspace/outputs_3d/<name>/`，并在检测到 Google Drive 桌面版时同步备份到 `GoogleOneAI_Studio/outputs_3d/<name>/`。

### 收工必查计费归零

```bash
~/.local/bin/colab sessions
~/.local/bin/colab usage
# 确认：Usage rate: 0.00/hr 且 Active assignments: 0
```

---

## 5. 实战踩过的 10 个核心坑与标准解法（已全部固化到脚本中）

以下是真实在 Colab L4 上从零打通两套模型时逐个排查并验证过的坑点清单，供自建 Notebook 或二次开发参考：

### 坑 1：Colab 默认镜像升级至 Python 3.13 + CUDA 13.0，导致 CUDA 扩展全挂
- **现象**：直接用系统 Python 装 `nvdiffrast`、`cumesh`、`o_voxel`、`custom_rasterizer` 报 C++ 标准/PyTorch ABI/NVCC 版本不兼容。
- **解法**：在 Colab VM 内用 `micromamba` 拉起独立隔离环境 **`/opt/mamba3d`**：
  - `python=3.11` + `cuda-toolkit=12.4.1`（`nvidia/label/cuda-12.4.1`）+ `gcc_linux-64=12` + `gxx_linux-64=12` + `ninja`
  - 锁死 `torch==2.6.0` + `torchvision==0.21.0`（`--index-url https://download.pytorch.org/whl/cu124`）
  - 显式导出 `CC`、`CXX`、`CUDAHOSTCXX` 指向 conda 的 GCC 12，防止混用宿主机高版本 GCC。

### 坑 2：长耗时任务用 `colab exec --timeout 0` 遇 SSL/网络瞬断会整条挂死
- **现象**：编译 + 推理持续 20~30 分钟，单条持久连接一旦遇到本地休眠或 SSL 抖动就会断线失联，甚至丢失关机信号。
- **解法**：改为 **「远程后台脱离进程（`start_new_session=True`）+ 短连接每 20 秒增量轮询 `/content/job.log` 字节偏移 + 命令重试 6~8 次 + `finally:` 强制 `colab stop` 5 次」**。

### 坑 3：CUDA 扩展编译全架构导致慢如蜗牛且吃爆内存
- **现象**：PyTorch 默认为多个算力架构并行编译，L4 VM 内存易 OOM。
- **解法**：固定 `TORCH_CUDA_ARCH_LIST="8.9"`（仅编译 Ada L4 架构）与 `MAX_JOBS="4"`。

### 坑 4：Jupyter 遗传环境变量导致 `matplotlib` 崩溃
- **现象**：Colab 默认环境带 `MPLBACKEND=module://matplotlib_inline.backend_inline`，后台无头 Python 导入 `matplotlib` 直接报错。
- **解法**：强制注入 `MPLBACKEND=Agg`。

### 坑 5：`MV-Adapter` 官方 `requirements.txt` 安装中断与隐含缺包
- **现象**：`requirements.txt` 里的 `nvdiffrast` 在 PEP517 隔离构建下找不到 `torch`；同时运行时还缺未写全的依赖。
- **解法**：过滤 `requirements.txt` 中的 `torch*` / `xformers` / `nvdiffrast`，改用 `--no-build-isolation` 单独装 `nvdiffrast`，并显式补齐 `jaxtyping`、`typeguard`、`kiui`、`matplotlib`、`scipy`、`imageio`、`timm`、`pyyaml`；同时修补 `inference_i2mv_sdxl.py` 中新版 `diffusers` 的 `pipe.vae.enable_slicing()` / `enable_tiling()`。

### 坑 6：`transformers 5.x` 破坏性更新同时击穿了两套模型
- **现象 A（`Hunyuan3D-2mv`）**：`transformers 5.x` 重构了 `DINOv2` 内部层命名，导致 `SingleImageEncoder` 加载权重键名不匹配。
  - **解法**：在所有 `pip install` 之后强制锁死 `transformers==4.46.3`、`diffusers==0.31.0`、`huggingface_hub>=0.25.0,<1.0.0`。
- **现象 B（`TRELLIS.2`）**：`TRELLIS.2` 的 `setup.sh` 默认拉到 `transformers 5.24.0`，移除了 `DINOv3ViTModel.layer` 属性，推理第一步即报 `AttributeError: 'DINOv3ViTModel' object has no attribute 'layer'`。
  - **解法**：强制锁死 **`transformers==4.57.6`** + `huggingface-hub>=0.34.0,<1.0.0` + `tokenizers>=0.22.0,<=0.23.0`，并在跑模型前执行 `DINOV3_LAYER_OK` 硬预检。

### 坑 7：`Hunyuan3DPaint` 的 `custom_rasterizer` 导入失败与找不到 `libc10.so`
- **现象**：用 `pip install -e .` 可编辑安装会导致部分路径钩子找不到编译好的 `.so`；即使找到 `.so`，动态链接器也会因找不到 `torch/lib/libc10.so` 报错。
- **解法**：对 `custom_rasterizer` 与 `differentiable_renderer` 使用**非可编辑正式安装**（`pip install . --no-build-isolation --no-deps`），将 `/opt/mamba3d/lib/python3.11/site-packages/torch/lib` 写入 `LD_LIBRARY_PATH`，并在流程前做 `CUSTOM_RASTERIZER_OK` 导入预检。

### 坑 8：`TRELLIS.2` 的隐藏第二个门控仓库 `briaai/RMBG-2.0`
- **现象**：很多人只申请了 `facebook/dinov3-vitl16-pretrain-lvd1689m`，进到 `Trellis2ImageTo3DPipeline.from_pretrained` 时才被 `briaai/RMBG-2.0` 403 拦下白烧点数。
- **解法**：开机前同时对两个仓库做 `curl -I` HTTP `200` 预检（详见第 3.2 节）。

### 坑 9：`TRELLIS.2` 稀疏注意力忽略 `sdpa` 且第三方 `flash_attn` 预编译包 ABI 错配
- **现象**：
  1. `trellis2/modules/sparse/config.py` 只认 `flash_attn` / `xformers` / `flash_attn_3`，传入 `SPARSE_ATTN_BACKEND=sdpa` 会被静默忽略并回退到 `flash_attn`；
  2. 从 GitHub 下载的第三方 `flash_attn-2.8.3.post2` 预编译 wheel 在 Colab 隔离环境下报 `undefined symbol: _ZN3c105ErrorC2...`（C++11 ABI 错配），而源码编译 `flash-attn` 在 L4 上耗时 30+ 分钟。
- **解法**：保留 `ATTN_BACKEND=sdpa`，将稀疏注意力设为 **`SPARSE_ATTN_BACKEND=xformers`**，安装与 `torch==2.6.0` + `cp311` 原生匹配的官方 **`xformers==0.0.29.post3 --no-deps`**（~5 秒秒装、零编译），并在启动推理前跑一条真实的 GPU 算子预检（`XFORMERS_CUDA_OK`）。

### 坑 10：OpenCV 5.1.0 默认无法读取 `forest.exr`，导致 `TRELLIS.2` 在导出 `.glb` 前崩掉
- **现象**：部分新版 `opencv-python-headless`（5.x）在读取 `TRELLIS.2/assets/hdri/forest.exr` 时返回 `None`，紧接着 `cv2.cvtColor(hdri_bgr, ...)` 抛异常，导致在 `o_voxel.postprocess.to_glb` 之前直接退出，30 分钟推理白跑。
- **解法**：
  1. **永远先导出 `trellis2_pbr.glb`**，再执行可选的转盘视频/网格图预览渲染；
  2. 将预览渲染包裹在 `try/except` 中，并在 `cv2.imread` 返回 `None` 时自动构造程序化柔光 `EnvMap` 张量兜底。
