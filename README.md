# 标书 UI 级 Hermes Agent 内部 Web 系统

这是第一版内部预审系统：浏览器上传招标文件、投标文件、资质/证书/业绩文件，系统抽取文本、必要时做 OCR，建立 SQLite 检索库，然后调用 Hermes Agent CLI 生成预审报告。

它是人工预审辅助工具，不是正式自动定分系统。

## 一、需要先安装什么

在公司电脑上先装这些：

1. Windows 10/11。
2. Git for Windows。
3. Python 3.12，安装时勾选 `Add python.exe to PATH`。
4. Hermes Agent Windows 原生版。
5. DeepSeek API Key。

本项目不要求 MySQL。第一版使用 SQLite，数据库文件在 `storage/app.db`。真实 PDF、Office 文件、数据库、日志、`.env`、`APIKEY.txt` 都不会上传 GitHub。

## 二、克隆代码

```powershell
cd C:\Users\你的用户名\Documents
git clone 你的GitHub仓库地址 bid-agent-web
cd bid-agent-web
```

如果是在当前这台电脑，本项目目录是：

```powershell
cd C:\Users\ajian\Documents\标书
```

## 三、安装 Python 依赖

第一版不强制建虚拟环境。直接使用系统 Python 3.12：

```powershell
py -3.12 -m pip install -r requirements.txt
```

如果公司电脑没有 `py` 命令，用 Python 3.12 的完整路径：

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m pip install -r requirements.txt
```

依赖里包含：

- `fastapi`、`uvicorn`：Web 服务。
- `jinja2`：服务端页面。
- `pdfplumber`、`pypdf`、`pymupdf`：PDF 文本抽取和扫描页渲染。
- `python-docx`：Word 文件抽取。
- `openpyxl`：Excel 文件抽取。
- `paddleocr==3.6.0`、`paddlepaddle==3.2.2`、`numpy<2.4`：OCR。这个版本组合已在当前 Windows + Python 3.12 上验证过。
- `pytest`：测试。

也可以直接运行安装脚本：

```powershell
.\scripts\install-windows.ps1
```

## 四、配置系统

这里有两层配置，不要混在一起：

- Hermes 自己的全局配置：决定模型、provider、DeepSeek API Key、工具、飞书/网关等能力。
- 本项目的 `.env`：只决定网页系统自己的登录密码、资料目录、数据库路径、OCR 开关，以及 `hermes` 命令路径。

复制配置模板：

```powershell
Copy-Item .env.example .env
notepad .env
```

至少改这几项：

```text
APP_PASSWORD=给同事登录网页用的密码
SESSION_SECRET=随便生成一串长随机字符
HERMES_COMMAND=hermes
OCR_ENABLED=true
REPORTS_DIR=reports
```

如果 `hermes` 命令不在 PATH，就把 `HERMES_COMMAND` 改成完整路径，例如：

```text
HERMES_COMMAND=C:\Users\你的用户名\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe
```

本项目 `.env` 不再保存 DeepSeek API Key，也不覆盖 Hermes 的 provider/model。模型统一由 Hermes CLI 自己的配置决定。

## 五、安装并配置 Hermes Agent

按 Hermes 官方 Windows 原生安装文档安装。安装后新开 PowerShell，先验证命令是否可用：

```powershell
hermes --version
```

然后配置 DeepSeek。推荐先走官方交互式配置：

```powershell
hermes setup
```

配置时按这个选：

```text
Setup 模式：Quick Setup
Model provider：DeepSeek
API Key：填你的 DeepSeek API Key
Base URL：https://api.deepseek.com
Model：deepseek-v4-pro
```

注意：DeepSeek 官方 Hermes 集成页在 setup 向导里写的是 Base URL 填 `https://api.deepseek.com`。如果你配置完成后看到 Hermes 自己写出的配置是 OpenAI/chat-completions 形态，不一定是错；以 `hermes -z` 的最小验证为准。当前本机曾验证通过的另一种形态是 `https://api.deepseek.com/anthropic` 加 `api_mode: "anthropic_messages"`。

如果已经装完 Hermes，但它还是默认配置，可以重新运行：

```powershell
hermes model
```

或者直接查看和编辑配置文件：

```powershell
hermes config path
hermes config env-path
hermes config show
hermes config edit
```

Windows 原生安装时，常见路径是：

```text
C:\Users\你的用户名\AppData\Local\hermes\config.yaml
C:\Users\你的用户名\AppData\Local\hermes\.env
```

当前已验证过的 DeepSeek 配置形态大致应包含：

```yaml
model:
  default: "deepseek-v4-pro"
  provider: "deepseek"
  base_url: "https://api.deepseek.com/anthropic"
  api_mode: "anthropic_messages"
```

密钥不要写进本项目代码，也不要上传 GitHub。用 `hermes setup` 或 `hermes model` 输入的 API Key 由 Hermes 自己保存，本项目不需要再存一份。

最后做 DeepSeek 最小验证：

```powershell
hermes -z "请只输出：Hermes DeepSeek 配置正常。"
```

如果这里不通，说明 Hermes 全局模型配置还没通，网页系统也不能完成 Hermes 预审，只能完成文件抽取和资料库检索。`--provider deepseek -m deepseek-v4-pro` 这类参数只建议临时排查时用，不作为本项目的默认调用方式。

## 六、运行测试

```powershell
py -3.12 -m pytest -q
.\scripts\doctor.ps1
```

`doctor.ps1` 会检查：

- Python 是否是 3.12。
- PDF、Word、Excel、OCR 依赖是否存在。
- 当前目录 PDF 是否能抽出文本。
- OCR 是否能识别一张自动生成的测试图片。
- Hermes 是否能显示版本、配置文件路径，以及能否用 Hermes 全局配置完成最小调用。

### 公司网络下的 OCR 模型下载

PaddleOCR 首次运行会下载模型，不是只安装 Python 包。需要能访问下面任意一个模型源：

```text
https://huggingface.co
https://modelscope.cn
https://aistudio.baidu.com
https://paddle-model-ecology.bj.bcebos.com
```

国内公司网络建议优先试 ModelScope 或百度 BOS。在当前 PowerShell 临时设置：

```powershell
$env:PADDLE_PDX_MODEL_SOURCE="modelscope"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True"
.\scripts\doctor.ps1
```

如果公司必须走代理，把代理也加上：

```powershell
$env:HTTP_PROXY="http://公司代理地址:端口"
$env:HTTPS_PROXY="http://公司代理地址:端口"
$env:PADDLE_PDX_MODEL_SOURCE="modelscope"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK="True"
.\scripts\doctor.ps1
```

如果代理需要账号密码，格式通常是：

```text
http://用户名:密码@公司代理地址:端口
```

这些配置也可以写进本项目 `.env`，但不要把带账号密码的 `.env` 上传 GitHub。模型下载成功后会缓存到：

```text
C:\Users\你的用户名\.paddlex\official_models
```

没有外网时，也可以从已下载成功的电脑复制这个目录到公司电脑同一路径。

## 七、启动网页

```powershell
.\scripts\run-dev.ps1
```

看到下面这类输出就说明服务已经启动成功：

```text
Uvicorn running on http://0.0.0.0:8000
```

这个 PowerShell 窗口不要关闭，关闭后网页服务也会停止。`0.0.0.0` 是服务监听地址，不是浏览器访问地址。

本机打开：

```text
http://127.0.0.1:8000
```

局域网同事访问：

```text
http://公司电脑IP:8000
```

公司电脑 IP 可以用下面命令查看，找当前网卡的 IPv4 地址：

```powershell
ipconfig
```

如果公司防火墙拦截，需要允许 Python 或端口 `8000` 的入站访问。

## 八、使用流程

1. 登录网页。
2. 新建项目。
3. 上传招标文件，类型选“招标文件”。
4. 上传投标文件，类型选“投标文件”。
5. 上传资质、证书、业绩、信用、商务报价等补充文件。
6. 文件表里确认“抽取”为 `completed`。
7. 如果显示 `failed`，点“重新抽取”，再进文件详情看错误信息。
8. 点击“启动 Hermes 预审”。
9. 在任务页查看运行日志、Hermes Prompt、预审报告。
10. 任务完成后，点击“打开报告目录”可在运行服务的电脑上打开该项目的报告文件夹。

## 九、报告目录规则

每个项目会在本地 `reports/` 目录下生成一个独立文件夹，格式为：

```text
reports/项目ID_项目名称/
```

例如：

```text
reports/002_台州市椒江区项目/
```

每次评审都会按“第几次 + 时间”保存 Prompt 和报告：

```text
第001次_20260609-143000_prompt.md
第001次_20260609-143000_report.md
第002次_20260609-151200_prompt.md
第002次_20260609-151200_report.md
```

报告文件开头也会写明项目、任务 ID、生成时间和第几次评审。

## 十、代码怎么分

- `bid_agent/app.py`：网页入口、登录、项目、资料库、上传、评审任务。
- `bid_agent/db.py`：SQLite 表、文件元数据、文本片段、FTS/LIKE 检索。
- `bid_agent/extractors.py`：PDF、Word、Excel、TXT、图片和 OCR 抽取。
- `bid_agent/document_service.py`：文件保存、抽取、重新抽取、写入检索库。
- `bid_agent/hermes.py`：生成 Hermes Prompt，调用 `hermes -z <prompt>`。provider、model 和 API Key 统一来自 Hermes CLI 自己的全局配置。
- `bid_agent/review.py`：评审任务编排，保存 Prompt 和报告。
- `bid_agent/templates/`：网页模板。
- `sample_data/`：可上传测试的假样例，不含真实标书。

## 十一、上传 GitHub 前检查

```powershell
git status --short
git check-ignore APIKEY.txt
git check-ignore *.pdf
git check-ignore storage/app.db
git check-ignore reports/
git check-ignore hermes-bid-eval-mvp/tender.pdf
```

真实文件和密钥应该都被 ignore。不要用 `git add -f` 强行上传真实标书或密钥。

## 十二、当前已知边界

- 普通 PDF 文本抽取已在当前两份真实 PDF 上验证通过。
- OCR 已在本机用 PaddleOCR 测试图片验证通过，首次运行会下载模型，比较慢。
- 商务报价缺少必要参数时报告必须写“无法计算”，不能编造分数。
- 证书真伪、信用状态、资质动态核查仍需人工或外部系统确认。

## 十三、Hermes 和本项目怎么分工

当前第一版不是把所有事情都交给 Hermes 做，而是把 Hermes 放在“评审推理执行器”的位置：

```text
本项目负责：登录、项目、上传、文件保存、文本抽取、OCR、SQLite 检索、候选证据筛选、Prompt 生成、报告归档
Hermes 负责：读取本项目给出的 Prompt 和证据，执行评审推理，输出 Markdown 预审报告
DeepSeek 负责：作为 Hermes 配置好的底层模型，完成语言理解和生成
```

所以 Hermes 参与了评审生成这一层，但资料库、OCR、项目管理、网页按钮、报告目录、任务记录这些是我们自己写的业务系统。这样做的原因是：标书预审需要强业务流程和可追溯资料库，单纯聊天机器人不方便管理项目、文件分类、页码证据和多次评审报告。

以后可以把 Hermes 参与度加深，例如接 Hermes API Server、MCP、Skills、Memory 或飞书网关。但第一版先保持可控：网页系统准备好证据，Hermes 只对这些证据做评审，不让它自由翻本机所有文件。

## 十四、飞书和成品前端

Hermes 支持飞书/Lark 等消息平台，也支持把 Hermes 暴露成 OpenAI-compatible API Server。因此有两类现成 UI 可以借：

1. 飞书机器人：适合当聊天入口、通知入口、让同事在群里问“某项目评审结果出来了吗”。但它不适合直接替代项目建档、批量上传、文件分类、报告目录管理。
2. Open WebUI、LobeChat、LibreChat、NextChat 等成品前端：适合通用聊天和工具调用。如果只是“和 Hermes 聊天”，可以接 Hermes API Server；但它们默认也不会替我们做标书项目管理、OCR、SQLite 证据库和评审报告归档。

推荐路线是：第一版继续用本项目网页做业务主入口；飞书先做消息通知和简单查询；如果后面要更像“真智能体平台”，再考虑 Hermes API Server + 成品前端，或把本项目能力封装成 Hermes 可调用的工具。

## 十五、关于“养”这个智能体

Hermes 官方宣传的自我学习，主要指它自己的记忆、技能和偏好会随使用积累。但本项目第一版不是让 Hermes 直接长期自由操作公司资料库，而是把 Hermes 当成一个可控的评审执行器：

```text
网页上传文件 -> 文本抽取/OCR -> SQLite 检索候选证据 -> 生成评审 Prompt -> 调用 Hermes CLI -> 保存 Prompt 和报告
```

也就是说，当前第一版已经有“可追溯的评审记录”，但还没有真正的“业务反馈闭环”。如果老板说要“养”，下一阶段不建议一上来就做模型微调，应该先做这几件事：

1. 增加人工反馈：每份报告可以标记“正确、错误、缺证据、引用不准、评分口径要改”。
2. 建立反馈库：把人工修正后的结论、证据和评分口径存进数据库。
3. 做 Prompt 版本管理：每次改评审规则和提示词都记录版本，能对比新旧效果。
4. 做标准样例集：保留一批脱敏假标书/历史样例，用来回归测试智能体有没有变好。
5. 再接 Hermes Skill/Memory：把稳定的评审经验沉淀成 Hermes skills 或项目规则，不让它随意把未经确认的结论写成“经验”。

所以“养”的下一层次不是让模型自己随便学习，而是“人工复核反馈 + 可审计知识库 + 规则版本化 + Hermes 记忆/技能沉淀”。这样才适合公司内部使用。
