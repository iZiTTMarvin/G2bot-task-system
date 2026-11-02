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

界面是**双 Agent 工作台**：左边选会话，中间跟 Agent 对话，右边是这一轮的任务。

1. 在「API 设置」选择 OpenAI 或 Anthropic 兼容格式，填写服务地址、API Key 和模型；生成与审核默认使用同一模型。
2. 左栏「生成 Agent」开一个会话，上传物料库（TXT/MD/CSV/XLSX）或直接说要做什么。
   **条数和步数都不用填**：条数由 Agent 按这套物料能支撑的互不重复活动决定，步数按 10–30 步自定。
3. Agent 回复里会写明生成了几条、哪几条需要人工处理，任务同时出现在右栏。
4. 右栏勾选任务点「送审」，自动切到「审核 Agent」会话：它按 Skill 逐条审、能改的直接改，回复里说明改了几条。
5. 点任务可在线查看：AI 审核意见、**AI 改了什么（+新增/−删去）**、步骤与物料都能直接编辑；改完点「确认」。
6. 勾选后「导出表格」，任意状态都能导，导出表带「状态」和「审核意见」两列。

审核 Agent 也可以单独用：粘贴一段任务文本（每行一步，物料用【物料名】标注）或上传文件，它就按 Skill 改。
所有消息都留档，历史对话会作为下一次生成的下文，所以「接着说」是有效的。

生成连接失败时，原任务集的要求和附件会保留；检查 API 设置后重新发一条即可。
已生成的任务不会因为失败而丢失，可以单条「重新审核」。

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
- `backend/app/services/conversations.py`、`chat.py`：会话与消息层（把一次性作业包装成可对话的工作台）。
- `frontend/`：三栏工作台（会话列表 / 对话 / 任务结果）。
- `skills/snapshot/`：从指定 `.kiro` 上游完整导入的规则、脚本与资源。
- `skills/generator/`、`skills/reviewer/`：两个独立角色的 Skill，共用领域规则。
- `data/`：本地数据库、附件、导出文件和模型配置。
- `docs/`：产品与接口设计资料，`openapi.json` 为当前契约（0.2.0）。

## 概念

- **会话（conversation）**：一个人话工作和一组任务的容器。两个 Agent 各有自己的会话列表。
- **批次（batch）**：后端容器，一个会话可以有多批；名称取用户第一句话，不再由模型命名。
- **任务（task）**：真正交付的东西，带完整版本链（AI 首次生成 / AI 审核优化 / 人工编辑）。
- **四态**：生成中 → 审核中 → 待确认 → 已确认。原来的 7 个内部状态仍保留在库里，界面只露这四态。
- **导出**：不要求「已确认」，任意状态都能导，靠表里的「状态」列区分。

正式模式由两个独立 Deep Agents 实例完成生成和审查，支持 Skill 加载、历史检索、物料汇总、确定性检查及有限修订。保留原有前后端契约、人工决定和版本记录。运行方式、规则更新、执行证据及验证限制见 [Deep Agents 实现说明](docs/DeepAgents实现.md)。
