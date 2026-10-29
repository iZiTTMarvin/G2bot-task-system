# G2 任务系统

本地 G2 遥操作采集任务生成与审核系统。后端使用 FastAPI + SQLite，前端使用 React + Vite + Ant Design。

## 启动

Windows 已安装 Python 3.12+ 和 Node 20+ 后，在 PowerShell 中运行：

```powershell
.\start.bat         # 正式模式，使用已配置的 OpenAI / Anthropic 兼容接口
.\start.bat demo    # 本地演示，使用后端 FakeModel
.\start.bat dev     # 开发模式，前端 5173、后端 8000
```

访问 <http://127.0.0.1:8000>。首次启动会安装依赖；正式模式和演示模式每次启动都会构建当前前端，构建失败不会启动服务。

如果 8000 已被占用，可以在启动前设置 `$env:G2_PORT = '8001'`，随后运行 `.\start.bat` 并访问对应端口。每个数据目录只能由一个服务实例使用；使用备用端口并行测试时，还需要通过 `G2_DATA_DIR` 指定独立数据目录。正常关闭时会等待当前后台作业结束，避免另一实例过早接管数据。

## 使用

1. 在「API 设置」选择 OpenAI 或 Anthropic 兼容格式，填写服务地址、API Key 和模型；生成与审核默认使用同一模型。地址可用服务根地址、带版本/代理前缀的 Base URL 或该格式的完整接口地址。
2. 在「任务生成」输入自然语言要求。可上传 TXT、MD、CSV、XLSX 场景库或物料库，也可以不上传。
3. 选择任务数量和步数范围，点击「生成」。AI 自动命名任务集和每条任务，结果直接显示在当前页面。
4. AI 审核员直接修复一般问题并保存优化版本，只有严重或优化后仍未解决的问题需人工处理。打开任务可查看独立审核卡片、编辑步骤和物料、按反馈重写、重新审核、通过或驳回。
5. 在「人工审核」筛选已通过任务并导出 XLSX。

生成连接失败时，原任务集的要求和附件会保留；检查 API 设置后点击「重新生成」。已有正文但审核失败时，打开任务点击「重新审核」，无需丢弃已生成内容。

前端只连接真实后端 `/api/v1`，不包含 Mock 数据或 Mock 控制台。

## 开发验证

```bash
cd backend && .venv/Scripts/python -m pytest
cd frontend && npm run typecheck && npm run lint && npm run build
```

后端单独启动：

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

目录：

- `backend/`：API、生成与审核作业、SQLite、模型客户端、规则校验和测试。
- `frontend/`：任务生成、任务集、人工审核和 API 设置。
- `skills/snapshot/`：规则校验脚本与规则快照。
- `data/`：本地数据库、附件、导出文件和模型配置。
- `docs/`：产品与接口设计资料。

已验证后端测试、前端类型检查、lint 与构建，以及隔离数据下的连接失败 → 刷新恢复 → 原任务集重新生成、OpenAI/Anthropic 本地 HTTP 协议 → 审核优化版本 → 人工通过流程和 390/768/1440px 审核详情布局。外部真实模型服务未在本次修改中调用；本地协议与确定性内容不能替代真实模型质量验收。
