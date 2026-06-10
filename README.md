# 标书 Hermes Agent 智能评审系统

本项目按五层架构重构，目标是让 **Hermes Agent 成为标书评审专家主体**，网页只负责上传、查看和人工复核。当前评审范围暂定为 **技术标预评审**：技术标满分 25 分，系统给出拟定技术分；资信、资格、商务报价、信用等非技术标因素暂按理想状态处理。

```text
文件解析层：把 PDF/Word/扫描件变成 Markdown/JSON/表格
向量库层：把资料切块、向量化、可语义检索
智能体层：Hermes 决定查什么、怎么评、怎么生成结论
模型层：DeepSeek / 本地大模型 / 私有化模型负责语言理解和推理
UI 层：网页只是给人上传、查看、复核
```

## 架构对应

- 文件解析层：`bid_agent/parsers.py`
  - TXT/Markdown：直接入库。
  - Word/Excel/PPTX：PaddleOCR doc2md 转 Markdown。
  - 招标文件/通用 PDF：可抽文字页走 PyMuPDF，低文字/扫描页渲染后走 PaddleOCR `PPStructureV3`。
  - 投标文件、资质/证书、业绩、信用、商务材料 PDF：默认逐页走 `PPStructureV3` 精细解析。
  - 图片/扫描件：PaddleOCR `PPStructureV3` 做版面、表格和 OCR 解析。
- 向量库层：`bid_agent/vector_store.py`
  - 本地 Qdrant，默认目录 `storage/qdrant`。
  - 中文 embedding 默认 `BAAI/bge-small-zh-v1.5`。
- 智能体层：Hermes + `bid-review` MCP
  - MCP server：`bid_agent/mcp_server.py`。
  - Hermes 可调用项目、文档分块、语义检索、重建向量、保存报告工具。
  - 当前 Hermes 角色定位为技术标评审专家，输出 25 分制拟定分数和扣分依据。
- 模型层：Hermes 全局模型配置
  - DeepSeek API Key / provider / model 不写进本项目。
  - 由 `hermes setup`、`hermes model`、`hermes config` 管理。
- UI 层：FastAPI/Jinja 工作台
  - 新建项目、上传资料、查看解析进度、查看向量状态、启动智能预审、查看报告。
  - 上传后后台解析，项目页会显示解析策略、阶段、页码进度和进度条。

## 开发机验证

在开发机改完、确认没问题后，再上传 GitHub：

```powershell
cd C:\Users\ajian\Documents\标书
py -3.12 -m pip install -r requirements.txt
py -3.12 -m pytest -q
.\scripts\doctor.ps1
```

下载或预热本地模型：

```powershell
.\scripts\download-local-models.ps1
```

如果模型源访问失败，先切国内源：

```powershell
$env:PADDLE_PDX_MODEL_SOURCE="modelscope"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True"
.\scripts\download-local-models.ps1
```

用脱敏 PDF 做深度解析验证：

```powershell
$env:PARSER_SMOKE_FILE="C:\path\to\sample.pdf"
.\scripts\doctor.ps1
```

本地启动网页：

```powershell
.\scripts\run-dev.ps1
```

浏览器打开：

```text
http://127.0.0.1:8000
```

不要在浏览器打开 `0.0.0.0:8000`；那只是服务监听地址。

## 上传 GitHub 后，公司电脑更新

先关闭公司电脑正在运行的 `scripts\run-dev.ps1` 窗口。

### 1. 拉取新版

进入项目目录并拉取 GitHub 最新代码：

```powershell
cd C:\Users\<用户名>\Documents\标书
git pull --ff-only origin main
```

如果公司电脑上的项目目录已经乱了，直接改名旧目录后重新克隆：

```powershell
cd C:\Users\<用户名>\Documents
Rename-Item -LiteralPath ".\标书" -NewName "标书_old_backup"
git clone <你的仓库地址> 标书
cd 标书
```

### 2. 删除旧版生成产物

删除旧版生成产物，不做迁移：

```powershell
Remove-Item -LiteralPath ".\storage" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath ".\reports" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath ".\hermes-bid-eval-mvp" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath ".\APIKEY.txt" -Force -ErrorAction SilentlyContinue
```

### 3. 安装依赖和配置

安装新版依赖：

```powershell
py -3.12 -m pip install -r requirements.txt
```

准备 `.env`：

```powershell
Copy-Item .env.example .env
notepad .env
```

关键配置：

```text
APP_PASSWORD=给同事登录网页用的密码
SESSION_SECRET=一串长随机字符
HERMES_COMMAND=hermes

DOCUMENT_PARSER=paddle_structure
DOCUMENT_LANGUAGE=ch

VECTOR_ENABLED=true
VECTOR_STORE_DIR=storage/qdrant
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DIM=512

APP_BASE_URL=http://127.0.0.1:8000
AGENT_TOOL_TOKEN=
```

### 4. 下载模型

下载本地模型：

```powershell
.\scripts\download-local-models.ps1
```

如果模型源访问失败，先切国内源再重试：

```powershell
$env:PADDLE_PDX_MODEL_SOURCE="modelscope"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True"
.\scripts\download-local-models.ps1
```

成功时应看到类似：

```text
Embedding model ready.
PPStructureV3 models ready.
Model cache locations:
```

### 5. 注册并验证 Hermes MCP

注册 Hermes MCP：

```powershell
.\scripts\register-hermes-mcp.ps1
```

验证 MCP 已启用：

```powershell
hermes mcp list
hermes mcp test bid-review
```

`hermes mcp list` 里应看到 `bid-review` 是 enabled。工具包括：

- `bid_list_projects`
- `bid_get_project`
- `bid_get_document_chunks`
- `bid_search_evidence`
- `bid_rebuild_vector_index`
- `bid_save_review_report`

`hermes mcp test bid-review` 应能连接成功并列出/发现工具；如果失败，先不要启动业务服务，优先检查 Hermes 安装、MCP 注册路径和 Python 依赖。

### 6. 启动前总体验证

启动服务前先跑诊断：

```powershell
.\scripts\doctor.ps1
```

重点看这些结果：

```text
ok paddleocr.PPStructureV3
ok paddlex[ocr] extras
ok paddleocr doc2md
ok local Qdrant client
ok MCP SDK
bid-review ... enabled
Hermes MCP bid-review test: 成功
```

如果要用一份脱敏 PDF 验证深度解析：

```powershell
$env:PARSER_SMOKE_FILE="C:\path\to\sample.pdf"
.\scripts\doctor.ps1
```

### 7. 启动服务并验证网页

启动：

```powershell
.\scripts\run-dev.ps1
```

浏览器打开：

```text
http://127.0.0.1:8000
```

服务启动后再开一个 PowerShell 窗口验证健康检查：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health
```

应返回：

```text
ok
```

如果服务窗口里显示 `Uvicorn running on http://0.0.0.0:8000`，浏览器仍然打开 `http://127.0.0.1:8000`；`0.0.0.0` 只是监听地址。

## 关于 `.paddlex` 缓存

`PPStructureV3` 是 PaddleOCR 暴露的结构化解析接口，但底层模型下载、管理和缓存由 PaddleX 管线负责，所以缓存目录叫：

```text
C:\Users\<用户名>\.paddlex\official_models
```

这不是换回旧 OCR。它是 PPStructureV3 所需的版面分析、表格识别、文本检测、文本识别等模型缓存。

建议公司电脑保留这个目录；删掉后下次解析 PDF/扫描件会重新下载。确实要强制重下：

```powershell
Remove-Item -LiteralPath "$env:USERPROFILE\.paddlex" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "$env:USERPROFILE\.paddleocr" -Recurse -Force -ErrorAction SilentlyContinue
```

## 使用流程

1. 登录网页。
2. 新建项目。
3. 上传招标文件、投标文件、资质/证书、业绩、信用、商务材料。
4. 系统后台解析为 Markdown/JSON，并在项目页显示当前阶段和页码进度。
5. 系统把文本块写入本地 Qdrant 向量库。
6. 点击“启动 Hermes 智能预审”。
7. Hermes 通过 `bid-review` MCP 主动检索技术标证据，给出 25 分制拟定技术分和扣分依据，并保存报告。
8. 网页查看报告，人工复核。

## 边界

- AI 结论是预审辅助，不是正式定分。
- 当前只评技术标，技术标满分按 25 分处理。
- 商务报价、资信、资格、信用等非技术标因素当前暂按理想状态处理，不在技术标报告中展开。
- 证书真伪、资质动态、信用状态、社保和外部系统核验必须人工确认。
- 默认不使用 TextIn 云 API，真实文件不出本机。
