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
- **解法**：调用长耗时脚本时务必加上 **`--timeout 0`**（`scripts/colab_cli_flux.py` 已默认配置 `--timeout 0` 并开启 `flush=True` 实时回显）。
