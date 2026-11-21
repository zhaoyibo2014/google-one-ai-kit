# Google One / Google AI Pro 全家桶权益最大化指南

> 开通 **Google AI Pro（\$19.99/月）** 后，不要只盯着 Gemini 聊天框。下面这份清单按「**如何直接变现为生产力**」拆解套餐内的每一项配套权益与额度（注：地区与账号期次不同，部分云盘容量或生活权益略有差异，以账号页面为准）。

---

## 1. Google Colab Pro（每月 200 计算单元）— 主力 GPU 算力池

- **怎么看余额**：进入任意 Colab 笔记本 -> 右上角 `Connect` 旁下拉箭头 -> **View resources**。
- **单价与消耗规律**（实际速率以面板实时显示为准）：
  | 运行时类型 | 适用场景 | 约消耗速率 | 200 单元约可用时长 |
  | :--- | :--- | :--- | :--- |
  | **CPU** | 下模型到 Drive、文本/数据处理 | **0 单元/小时** | 无限免费 |
  | **T4 (16 GB)** | 轻量推理、开源 TTS（CosyVoice 等） | ~1.1 ~ 2.0 单元/小时 | ~100+ 小时 |
  | **L4 (24 GB)** | **FLUX.1 FP8 ComfyUI 出图、ai-toolkit 训 LoRA** | ~1.5 ~ 3.0 单元/小时 | ~70 ~ 120 小时 |
  | **A100 (40/80 GB)** | 高速 LoRA 训练、全精度大模型推理 | ~7 ~ 15 单元/小时 | ~13 ~ 28 小时 |
- **铁律**：用完必须点 **`Runtime -> Disconnect and delete runtime`**（或在 `Manage sessions` 终止），否则闲置也会按分钟扣点。

---

## 2. Google Drive（5 TB 大容量云存储）— 零本地占用的云端模型仓

- **正确用法**：桌面端登录时勾选 **Stream files（流式传输）**、跳过本地目录备份。
- **价值**：
  - 存放动辄 15~30 GB 的 FLUX / SDXL / LoRA / TTS 权重和 ComfyUI 产出图，**不吃 Mac/PC 本地固态硬盘**。
  - Colab 挂载 Drive 后零拷贝读取，重开虚拟机秒级恢复环境，不用每次重下几十 GB 模型。

---

## 3. 每月 \$10 Google Cloud / GenAI 开发者额度（最容易白白浪费！）

- **注意**：这 \$10 **不会自动出现在 AI Studio 免费额度里**，需要手动激活：
  1. 用同一 Google 账号登录 **Google Developer Program** 门户。
  2. 领取每月 **\$10 Google Cloud / GenAI credits**（按月发放，通常可累计且有效期最长 12 个月）。
  3. 绑定到你的 **Google Cloud Billing** 账号并关联 **Google AI Studio** API Key。
- **最划算用法**：调用 Gemini 原生生图 API（如 Flash Image / Imagen，Batch 模式半价约 \$0.017~0.034/张），**每月 \$10 能低成本批产 150~300 张高一致性概念图、图标、UI 贴图**，再送进本地或 Colab 工作流二次精修。

---

## 4. Google Flow（每月 1,000 Credits）+ Whisk — 灵感与宣传视频引擎

- **Whisk（零代码风格混音器）**：
  - 把目标画风图放进 **Style** 槽，把草图/构图放进 **Subject/Scene** 槽，快速批量探索新角色、场景变体——**先在 Whisk 跑出几十张高一致性种子图，再攒进 LoRA 训练集，比在 Colab 硬试错省点数得多**。
- **Google Flow（1,000 Credits/月，集成 Veo 视频能力）**：
  - 适合把 ComfyUI 生成的高清设定图直接转成动态展示视频、项目宣传 PV、商品/游戏动态海报。

---

## 5. Google Antigravity + Gemini CLI + Jules — 编码与工程自动化

- **Antigravity / Gemini CLI**：Pro 会员享有更高的速率与调用额度，直接用来写数据处理脚本、改造工作流、接管浏览器自动执行 Colab。
- **Jules（GitHub 异步 Agent）**：绑定 GitHub 仓库后，可把写测试、整理文档、批量修 lint 等独立任务丢给它在后台跑完直接提 PR。

---

## 6. NotebookLM（5x 额度）+ Gemini App（100 万上下文）

- **NotebookLM**：把整套项目文档、美术设定集、技术规范 PDF 丢进去，生成结构化检索笔记和语音播客概览。
- **Gemini App**：在网页端零成本头脑风暴、打磨英文自然语言 FLUX 提示词模板（省下 API 额度）。
