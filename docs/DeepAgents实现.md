# Deep Agents 运行与规则维护

正式模型通路使用 Deep Agents 0.7.32，生成与审查分别创建 Agent，使用独立上下文、角色 Skill 和工具证据。Provider、服务地址和模型继续来自设置页，保持 OpenAI Chat Completions 与 Anthropic Messages 两种格式。

## 启动与使用

照常运行 `start.bat`；已有虚拟环境也会检查当前依赖。正式模型服务必须支持工具调用，结构化结果通过工具协议返回。只有文本补全能力的接口会明确失败，不会退回旧 HTTP 通路。

`start.bat demo` 仍使用确定性的 FakeModel 演示业务流程，不验证 Deep Agents 或模型质量。

旧 HTTP 客户端已移除。历史任务、版本、审核和人工决定保留。旧批次如果只有不完整的规则快照，不能伪装成已冻结新 Skill 后继续调用新 Agent；此时会提示新建批次。原任务与记录仍可读取，不自动迁移或重新生成。

## 一次运行做什么

1. 后台作业根据批次的规则编号读取已冻结文件，校验运行所需规则和角色文件。
2. 生成 Agent 加载 `g2-task-generator`，按活动、初态、终态写任务；没有物料库时可选常见物品，不得声称现场库存已核验。
3. Agent 调用 `check_tasks` 检查整个候选批次。未填写物料时根据步骤中的【】自动汇总；单任务规则和同批比较结果分别提供。
4. 检查工具返回正文 SHA-256 作为 candidate_id。结构化提交只引用这个编号，运行时取回已检查的完整草稿，避免模型重复抄写正文引入差异。
5. 审查 Agent 加载 `g2-task-reviewer`，从正文、目标和同批当前任务重新判断。全部审核结束后重新比较当前批次；修改后的版本单独保存。
6. 文字步骤完全相同（不计顺序）阻断确认；骨架近似只做提示，不因模型猜测相似就阻断。人工复核与导出继续沿用原有流程。

Skill、提示词和工具各司其职：角色提示词规定职责与输出协议，Skill 规定工作方法，共享领域规则提供约束，工具执行确定性计算。脚本通过不能证明活动有意义、五套库存齐备、夹爪可执行或时长达到要求。

## 运行范围与状态

- 使用 SDK 的 `SkillsMiddleware` 加载并显式固定当前角色 Skill；`MemoryMiddleware` 注入核心原则，其他参考按需读取。
- 生成和改写不检索历史任务库；同批对比只读取本批任务的当前版本。`compare_step_matches` 只核算提供的一对一配对，不能证明语义相同或现场可行。
- SDK 的文件 backend 为本次调用的 `StateBackend`，只装入规则包。只开放 `ls/read_file/glob/grep` 和业务工具，不开放主机文件或 shell。
- 通过模型的精确 HarnessProfile 关闭通用子代理，且不暴露 `task/execute/write_file/edit_file/delete`。没有经理、Swarm 或跨 Agent 聊天共享。
- `write_todos` 只管理本次 Agent 内部计划；任务版本、审核、作业和人工决定仍由 SQLite 负责。
- 每次调用使用独立 `InMemorySaver` 和 thread id，在工具循环与补交之间保留上下文；不是跨进程恢复或长期记忆。进程重启仍按既有规则将未完成作业标记为中断。
- 每个 Agent 最多 24 次模型调用、64 次工具调用。首次检查后最多三轮再次检查；SDK 请求超时 120 秒，不自动重试服务端请求。
- 认证、限流、超时和连接失败沿用既有错误码；服务商原始错误文本与密钥不回显。工具异常为技术失败，不会被当成质量通过。

## 更新 Skill

完整上游为 `C:\Users\xuhaochen\.agents\skills\g2-robot-task-designer-v2`。同步不修改上游或自动写历史台账。

停止服务后，在仓库根目录执行：

```powershell
& backend\.venv\Scripts\python.exe backend\scripts\sync_skills.py 'C:\Users\xuhaochen\.agents\skills\g2-robot-task-designer-v2'
Push-Location backend
$ruleDir = & .\.venv\Scripts\python.exe -c "from app.tools.skill_bundle import freeze_bundle; print(freeze_bundle().root)"
Pop-Location
python -B (Join-Path $ruleDir 'scripts/regression.py')
python -B (Join-Path $ruleDir 'scripts/segment_overlap_regression.py')
& backend\.venv\Scripts\python.exe -m pytest backend\tests -q
```

Skill 完整回归使用含 `pandas` 和 `openpyxl` 的 Python 环境。项目运行本身不依赖 `pandas`；运行包由清单冻结，保留在旧目录中的历史资产不会复制到运行包。修改角色 Skill 前应先冻结当前规则包；如果旧包没有归档且文件已被改动，同步器会拒绝将改动后的文件冒充旧快照。

同步器复制源文件并记录全部文件及两个角色 Skill 的 SHA-256。旧版专有资产保留在本地，不纳入新版清单或运行时资料。角色 Skill 修改后也要重跑同步器更新清单。Git 通过 `.gitattributes` 保持 Skill 文件字节，避免检出时行尾转换破坏哈希。

两个角色入口与共享 `snapshot/` 是共同安装的运行包，不能只复制一个入口文件后声称资源齐备。运行时将共享源 Skill 的核心原则映射到 `/rules/SKILL.md`，其原有聊天交付、导出、台账回写和自我进化流程由系统职责接管；完整源文件仍在仓库快照中保留。

新建批次时将运行所需规则、资源及角色 Skill 冻结到 `data/rule-snapshots/<rule_snapshot_id>/`，后续调用和校验都按该编号加载。规则目录更新不会改变已冻结批次。快照缺失或所需文件哈希不符时返回 `RULE_TOOL_FAILED`，不借用当前规则冒充旧版本；旧版历史任务资产不参与运行或完整性检查。

## 查看执行证据

每个 Agent 调用写入 `data/agent-traces/<run_id>/<role>-<id>.jsonl`；独立验证脚本的调用位于其隔离数据目录下。

记录包括实际进入模型上下文的 Skill、共享规则路径、工具启动与执行结果摘要、检查过的正文 SHA-256、补交和完成或失败。记录不包含 API Key、原始服务商响应或私有推理。任务正文、审核结果和正式版本继续由业务数据库保存，轨迹只用于核对 Agent 运行。

## 验证

```powershell
& backend\.venv\Scripts\python.exe -m pytest backend\tests -q
& backend\.venv\Scripts\python.exe -m pip check
```

以下是 2026-10-30 的历史验证记录，不代表新版规则接入后的质量结论：

- 后端 86 项测试通过，覆盖既有业务流程与新增 Agent 集成。
- 用脚本模型驱动真实 SDK 图，验证 Skill/核心规则加载、错误草稿检查、修订后重查、角色隔离、执行预算，以及跳过检查或检查后改稿不能直接提交。
- 用本地 HTTP 服务验证 OpenAI、Anthropic 两种实际 SDK 协议、工具结果往返、完整接口与自定义版本路径、认证、限流和服务错误语义。
- 冻结快照后修改源规则不会影响该批次；损坏快照不会假通过。
- API 作业通过两个真实 SDK 图和本地 HTTP 服务完成生成、独立审查、版本保存及人工通过；规则工具故障保留错误分类。固定事件同步的回归测试验证失败终态只在任务解除占用后发布。
- 指定上游的 33 条规则回归及连续段重叠回归通过；Python 依赖一致性检查通过。
- 前端源码和前后端契约未改，本轮未重复进行浏览器或前端构建验收。

## 真实模型样本

使用设置中原有的 `deepseek/deepseek-v4.1-flash`，同一份“为同一个人外出办公备好电脑包”输入，对比原 HTTP 生成/审核与新的生成/审核通路。验证数据放在隔离目录，不写业务任务、设置或外部历史台账。

| 本次样本 | 原 HTTP 通路 | Deep Agents 通路 |
| --- | --- | --- |
| 生成与审核 | 完成 | 完成，实际加载两个独立 Skill 并调用业务工具 |
| 最终文本规则检查 | passed | passed |
| 总耗时 | 41.64 秒 | 384.35 秒 |
| 审核可观察行为 | 对线缆盘绕给出风险提醒 | 修订插头压入线圈等操作，列出现场适配、五套库存与历史近似的待核验项 |

本地原始结果：`data/agent-validation/real-comparison/comparison.json`；对应轨迹位于同目录的 `agent-traces/standalone/`。旧通路仅在隔离对照脚本中从 Git 基线载入，应用中没有旧客户端或运行时回退。

第一次真实验证发现“检查后重抄正文导致内容变化”，随后改为提交已检查候选编号，再跑通当时的通路。

这证明框架和工具闭环已运行，不证明整体质量已经提升。新通路在本样本中明显更慢；重复折线等动作的必要性仍需人工判断，五套物料、夹爪适配和实际时长仍未现场验证。

## 当前业务与规则来源

业务边界见 [当前行为契约（0.3.0）](./当前行为契约.md)。当前资料按会话引用、按批次冻结；人工核验决定绑定具体版本，模型不能代填现场证据。项目脚本修订在 `skills/overrides/` 维护，再运行 `backend/scripts/sync_skills.py --local` 归档并生成规则清单；不改全局上游 Skill。轨迹增加模型调用开始、结束和耗时事件，统计脚本不将旧轨迹或演示模型当成已测调用。
