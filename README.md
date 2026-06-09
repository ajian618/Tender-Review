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

复制配置模板：

```powershell
Copy-Item .env.example .env
notepad .env
```

至少改这几项：

```text
APP_PASSWORD=给同事登录网页用的密码
SESSION_SECRET=随便生成一串长随机字符
DEEPSEEK_API_KEY=你的DeepSeek密钥
DEEPSEEK_BASE_URL=https://api.deepseek.com/anthropic
HERMES_COMMAND=hermes
OCR_ENABLED=true
REPORTS_DIR=reports
```

如果 `hermes` 命令不在 PATH，就把 `HERMES_COMMAND` 改成完整路径。

## 五、安装并验证 Hermes Agent

按 Hermes 官方 Windows 原生安装文档安装。安装后新开 PowerShell，验证：

```powershell
hermes --version
hermes -z "请只输出：Hermes Windows 原生运行正常。"
```

如果这里不通，网页系统也不能完成 Hermes 预审，只能完成文件抽取和资料库检索。

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
- Hermes 是否能显示版本。

## 七、启动网页

```powershell
.\scripts\run-dev.ps1
```

本机打开：

```text
http://127.0.0.1:8000
```

局域网同事访问：

```text
http://公司电脑IP:8000
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
- `bid_agent/hermes.py`：生成 Hermes Prompt，调用 `hermes -z`。
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
