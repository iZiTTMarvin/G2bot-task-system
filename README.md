# G2 任务系统

本地 G2 遥操作采集任务生成与审核系统。后端使用 FastAPI + SQLite + Deep Agents，前端使用 React + Vite + Ant Design。

## 启动

Windows 已安装 Python 3.12+ 和 Node 20+ 后，在 PowerShell 中运行：

```powershell
.\start.bat         # 正式模式，使用已配置的 OpenAI / Anthropic 兼容接口
.\start.bat demo    # 本地演示，使用后端 FakeModel
.\start.bat dev     # 开发模式，前端 5173、后端 8000
```

访问 <http://127.0.0.1:8000>。启动时检查并安装当前依赖；正式模式和演示模式每次启动都会构建当前前端，构建失败不会启动服务。

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

- `backend/`：API、生成与审核作业、SQLite、Deep Agents 运行入口、规则工具和测试。
- `frontend/`：任务生成、任务集、人工审核和 API 设置。
- `skills/snapshot/`：从指定 `.kiro` 上游完整导入的规则、脚本与资源。
- `skills/generator/`、`skills/reviewer/`：两个独立角色的 Skill，共用领域规则。
- `data/`：本地数据库、附件、导出文件和模型配置。
- `docs/`：产品与接口设计资料。

正式模式由两个独立 Deep Agents 实例完成生成和审查，支持 Skill 加载、历史检索、物料汇总、确定性检查及有限修订。保留原有前后端契约、人工决定和版本记录。运行方式、规则更新、执行证据及验证限制见 [Deep Agents 实现说明](docs/DeepAgents实现.md)。
