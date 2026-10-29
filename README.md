# G2 任务系统

本地 G2 遥操作采集任务生成与审核系统。后端使用 FastAPI + SQLite，前端使用 React + Vite + Ant Design。

## 启动

Windows 已安装 Python 3.12+ 和 Node 20+ 后，在 PowerShell 中运行：

```powershell
.\start.bat         # 正式模式，使用 OpenAI 兼容模型接口
.\start.bat demo    # 本地演示，使用后端 FakeModel
.\start.bat dev     # 开发模式，前端 5173、后端 8000
```

访问 <http://127.0.0.1:8000>。首次启动会安装依赖并构建前端。

## 使用

1. 在「API 设置」填写 Base URL、API Key 和模型；生成与审核默认使用同一模型。
2. 在「任务生成」输入自然语言要求。可上传 TXT、MD、CSV、XLSX 场景库或物料库，也可以不上传。
3. 选择任务数量和步数范围，点击「生成」。AI 自动命名任务集和每条任务，结果直接显示在当前页面。
4. 打开任务可编辑步骤和物料、按反馈重写、重新审核、通过或驳回。
5. 在「人工审核」筛选已通过任务并导出 XLSX。

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

已验证后端测试、前端类型检查与构建，以及隔离数据下的上传 → 生成 → 任务详情 → 人工通过 → XLSX 下载流程。外部真实模型服务未在本次修改中调用；模型协议由单元测试覆盖。
