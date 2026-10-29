# G2 任务系统（本地 Demo）

一个生成 Agent + 一个审核 Agent + 人工审核闭环的本地任务系统。后端 Python/FastAPI + SQLite，前端 React + Vite + Ant Design。

**当前状态**：Demo 开发基线已实现并完成本地联调；**真实模型接入未验收**（无可用凭据，模型通路以 OpenAI 兼容 HTTP 客户端实现 + 无凭据演示模式验证）。设计与接口文档见 [docs/](./docs/)。

## 快速开始（Windows，需已安装 Python 3.12+ 与 Node 20+）

在 PowerShell 中（注意必须带 `.\` 前缀，PowerShell 不从当前目录找命令）：

```powershell
.\start.bat demo    # 演示模式：不需要模型凭据，用确定性 FakeModel 走通全流程
.\start.bat         # 正式模式：启动后在「设置」页填写 OpenAI 兼容地址/密钥/模型名
.\start.bat dev     # 开发模式：Vite 热重载(5173) + 后端(8000)
```

在传统 cmd 中直接 `start.bat demo` 即可。

演示/正式模式都访问 <http://127.0.0.1:8000>（FastAPI 托管前端构建产物）。首次启动会自动创建虚拟环境、安装依赖并构建前端。

> 未在干净机器上验证过一键安装；以上命令在开发机（Python 3.13 / Node 22）验证通过。

## 使用流程

1. **设置**（正式模式）：填写 OpenAI 兼容 base_url、API Key、生成/审核模型名。密钥存本地 `data/config/`，接口只回「已设置」。
2. **资料**：上传 TXT/MD/CSV/XLSX（≤5 MiB、5 万字、2 万单元格；XLSX 公式会被拒绝），查看解析预览。
3. **任务生成**：创建批次（目标、1–10 条、普通 10–20 步 / 长任务 20–30 步、资料），点击生成。后台作业生成 → 规则校验 → 逐条 AI 审核；页面关闭不取消作业。
4. **人工审核**：按状态页签处理；抽屉内编辑步骤/物料、保存新版本、通过/驳回（驳回必须写理由）、重新 AI 审核、按反馈重写；可对照 AI 原稿与当前稿。
5. **导出**：在「已通过」页签勾选同一批次任务导出三列 XLSX（任务名字/任务步骤/单套所需物料）。

前端默认 Mock 模式（顶栏有橙色标识 + Mock 控制台可注入故障场景）；联调时切到「真实」。

## 开发

```bash
# 后端测试（32 项，覆盖批次验收）
cd backend && .venv/Scripts/python -m pytest

# 前端
cd frontend && npm run typecheck && npm run build

# 后端单独启动
cd backend && .venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

目录约定：

- `backend/` FastAPI 应用（api/services/agents/tools 分层）、pytest
- `frontend/` React + Vite + AntD；`src/api/` 内 real 与 mock 同接口
- `skills/snapshot/` 外部规则 Skill 只读快照（validate_tasks + materials + 规则文件，MANIFEST 记录哈希；`rule_snapshot_id`）
- `data/`（gitignored）SQLite、上传附件、导出文件、模型配置
- `docs/` 设计基线：蓝图、接口契约、OpenAPI 0.1.0、双人实施清单

## 已验证 / 未验证

已验证（2026-10-28/29，本机）：

- 后端 pytest 32 项全绿（幂等、revision 冲突、状态机、部分失败保留、恢复、导出内容）
- 浏览器真实联调：列表 → 详情 → 编辑 → 保存并通过 → 已通过导出 XLSX（含人工修改稿）
- 重启恢复：interrupted 作业释放占用、任务转 review_failed、可手动重审（测试覆盖）

未验证 / 已知限制：

- **真实模型调用未验收**（无凭据）。`OpenAIModelClient` 错误分类（超时/限流/认证/协议）只经单元路径与 FakeModel 验证。
- Deep Agents SDK 未接入运行时（已安装 0.7.32 可选依赖；当前通路为 OpenAI 兼容 HTTP）。
- 规则快照的历史台账去重未启用（`ledger_sigs` 为空）；导出不回写外部台账。
- 干净机器一键安装未验证。
