# G2 工作台前端

React、TypeScript、Vite、Tailwind v4、shadcn/ui 与 AI Elements。通过现有 `/api/v1` REST 接口连接 FastAPI，不引入另一套聊天服务或业务状态源。

## 开发与验证

```powershell
npm ci
npm run dev
npm test
npm run lint
npm run typecheck
npm run build
```

开发服务器将 `/api` 代理到 `http://127.0.0.1:8000`，需另行启动后端。测试使用 Node 内置运行器及 TypeScript strip，验证环境为 Node 22.20。生产构建输出到 `dist/`，由后端托管。

## 职责

- `src/App.tsx`：窗口布局、导航、主题、所选任务及跨面板操作。
- `src/hooks/use-workspace.ts`：会话读取、按会话保留的页面草稿、附件、发送、重试与后台作业轮询。
- `src/components/ChatPanel.tsx`：需求输入、消息和执行反馈。
- `src/components/TaskPanel.tsx`：结果筛选、选择、送审和导出入口。
- `src/components/TaskDetailDrawer.tsx`：版本编辑、规则问题、人工核验、决定及历史恢复。
- `src/components/MaterialLibrary.tsx`、`src/pages/SettingsPage.tsx`：资料和模型设置。
- `src/lib/presentation.ts`：消息去重、资料继承、逐项证据映射等纯逻辑；`tests/` 提供回归。

布局与状态归属见 [DESIGN.md](./DESIGN.md)，浏览器验收见 [UI 架构重构验收](../docs/UI架构重构验收.md)。草稿只在当前页面内保留，刷新或关闭前提示未提交内容，不跨刷新持久化。

## 组件来源与维护

基础控件来自 [shadcn/ui 官方 registry](https://ui.shadcn.com/docs/installation/vite)，配置见 `components.json`。Conversation、Message、PromptInput 来自 [Vercel AI Elements](https://github.com/vercel/ai-elements) 官方 registry，源码纳入 `src/components/ai-elements/`。`ai` 仅提供类型，网络请求仍由已有 API client 执行。

组件源码由项目维护，重新生成前需检查以下局部适配：

- PromptInput 在提交成功后才重置，失败保留输入与附件；业务层额外防护输入法组合结束后的误发送。
- Message 保留已使用的消息容器与动作，移除未使用的 Markdown、代码、公式和分支渲染；Conversation 移除未使用的下载辅助逻辑。
- Button 默认 `type="button"`，表单显式使用 submit；关闭文案中文化，过渡限定具体属性，补充任务页签可见焦点。

升级时先核对官方变更，再合并必要修复，并验证输入、焦点、浮层和失败恢复。
