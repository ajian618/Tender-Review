# 标书资料后台 + Hermes Agent

本项目的主体是 **Hermes Agent**。网页只是资料后台，用来上传、解析、清理、重建索引和查看报告；评审、查询、经验沉淀默认从 Hermes CLI/桌面端/后续飞书入口发起。

## 架构边界

```text
资料后台：FastAPI/Jinja，管理项目、文件、解析、清理、报告查看
资料库：SQLite，保存项目、文档、分片、任务、报告记录、经验
向量库：本地 Qdrant，保存文档分片向量
智能体：Hermes，通过 bid-review MCP 直连 SQLite/Qdrant/经验库
模型：由 Hermes 全局配置管理，例如 DeepSeek 或私有模型
```

`bid-review` MCP 不再转发 FastAPI HTTP 接口。只要资料已经解析入库，网页服务不启动时，Hermes 也能直接读取 SQLite/Qdrant 并保存报告或经验。

## 本机验证

```powershell
cd C:\Users\ajian\Documents\标书
py -3.12 -m pip install -r requirements.txt
py -3.12 -m pytest -q
.\scripts\register-hermes-mcp.ps1
.\scripts\doctor.ps1
```

期望看到：

```text
23 passed
MCP_DATA_ACCESS=direct SQLite/Qdrant/agent_lessons
Hermes MCP bid-review test: 成功
Tools discovered: 11
```

## 日常使用

需要上传、删除、重解析资料时才启动网页后台：

```powershell
cd C:\Users\ajian\Documents\标书
.\scripts\run-dev.ps1
```

浏览器打开：

```text
http://127.0.0.1:8000
```

资料已经在库里时，不需要启动网页。直接打开 Hermes CLI：

```powershell
cd C:\Users\ajian\Documents\标书
hermes
```

可以这样发任务：

```text
使用 bid-review 工具列出当前项目。
读取 1 号项目，检查资料是否解析完成。
检索技术标评分办法、施工组织设计、质量安全进度和水利场景相关证据。
如形成可复用经验，保存到 bid_save_agent_lesson。
生成技术标 25 分制预评审报告并保存。
```

## MCP 工具

Hermes 可用工具：

```text
bid_list_projects
bid_get_project
bid_get_document_chunks
bid_search_evidence
bid_rebuild_vector_index
bid_create_review_job
bid_get_review_job
bid_update_review_job
bid_save_review_report
bid_search_agent_lessons
bid_save_agent_lesson
```

## 公司电脑更新

先关闭公司电脑上正在运行的 `scripts\run-dev.ps1` 窗口，并结束旧的 Hermes CLI/桌面端会话。

已有项目目录时执行：

```powershell
cd C:\Users\<公司用户名>\Documents\标书
git pull --ff-only origin main
py -3.12 -m pip install -r requirements.txt
.\scripts\register-hermes-mcp.ps1
.\scripts\doctor.ps1
```

`register-hermes-mcp.ps1` 会重写 Hermes 的 `bid-review` MCP 配置，把它指向当前项目里的 `scripts\bid-review-mcp.cmd`。这一步就是本次大改涉及的 Hermes 命令行配置更新；一般不需要重新配置 DeepSeek API Key 或 Hermes 默认模型。

如果 `git pull --ff-only origin main` 失败，说明公司电脑目录有本地改动或目录状态混乱。保守处理方式：

```powershell
cd C:\Users\<公司用户名>\Documents
Rename-Item -LiteralPath ".\标书" -NewName "标书_old_backup"
git clone <你的仓库地址> 标书
cd 标书
py -3.12 -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
.\scripts\register-hermes-mcp.ps1
.\scripts\doctor.ps1
```

`.env` 至少确认这些值：

```text
APP_PASSWORD=网页登录密码
SESSION_SECRET=一串长随机字符
STORAGE_DIR=storage
REPORTS_DIR=reports
DATABASE_URL=sqlite:///storage/app.db
VECTOR_ENABLED=true
VECTOR_STORE_DIR=storage/qdrant
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
EMBEDDING_DIM=512
```

更新成功后，重新打开一个新的 Hermes 会话：

```powershell
cd C:\Users\<公司用户名>\Documents\标书
hermes
```

然后先让 Hermes 自检：

```text
使用 bid-review 工具列出项目，并说明当前 MCP 是否能直连资料库。
```

## 边界

- 当前只做技术标预评审，技术标按 25 分处理。
- 商务报价、资信、资格、信用等后续单独扩展。
- 网页不再作为评审发起入口；网页只是资料后台。
- AI 结论是预审辅助，正式定分仍需人工确认。
