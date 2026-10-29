import {
  Alert,
  Button,
  Empty,
  Input,
  InputNumber,
  Progress,
  Select,
  Spin,
  Upload,
  message,
} from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ApiClient } from '../api/client';
import { newIdempotencyKey } from '../api/client';
import type { ApiError } from '../api/errors';
import type { AttachmentSummary, Batch, Run, TaskSummary } from '../api/types';
import TaskDrawer from '../components/TaskDrawer';
import TaskStatusTag from '../components/TaskStatusTag';

interface Props {
  api: ApiClient;
}

const STAGE_LABEL: Record<Run['stage'], string> = {
  queued: '等待生成',
  generating: 'AI 正在命名并生成任务',
  validating: '正在校验任务',
  reviewing: 'AI 审核员正在审查与优化任务',
  done: '生成完成',
};

function runLabel(run: Run): string {
  if (run.status !== 'queued' && run.status !== 'running') {
    if (run.kind === 'review_task') return run.status === 'succeeded' ? '审核完成' : '审核失败';
    if (run.kind === 'revise_task') return run.status === 'succeeded' ? '重写完成' : '重写失败';
    return run.status === 'succeeded' ? '生成完成' : '生成失败';
  }
  if (run.stage === 'queued' && run.kind !== 'generate_batch') return '等待处理任务';
  if (run.stage === 'generating' && run.kind === 'revise_task') return 'AI 正在按反馈重写任务';
  return STAGE_LABEL[run.stage];
}

export default function GeneratePage({ api }: Props) {
  const [prompt, setPrompt] = useState('');
  const [taskCount, setTaskCount] = useState(3);
  const [taskMode, setTaskMode] = useState<'standard' | 'long'>('standard');
  const [attachments, setAttachments] = useState<AttachmentSummary[]>([]);
  const [attachmentIds, setAttachmentIds] = useState<string[]>([]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState<string | null>(null);
  const selectedBatchIdRef = useRef<string | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [openTaskId, setOpenTaskId] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selectBatch = useCallback((batchId: string) => {
    selectedBatchIdRef.current = batchId;
    setSelectedBatchId(batchId);
  }, []);

  const loadTasks = useCallback(
    async (batchId: string) => {
      try {
        const result = await api.listTasks({ batch_id: batchId, page_size: 100 });
        if (selectedBatchIdRef.current === batchId) {
          setTasks([...result.items].sort((a, b) => a.seq - b.seq));
        }
      } catch (cause) {
        if (selectedBatchIdRef.current === batchId) setError((cause as ApiError).message);
      }
    },
    [api]
  );

  const loadBatches = useCallback(async () => {
    const result = await api.listBatches(1, 100);
    setBatches(result.items);
    return result.items;
  }, [api]);

  useEffect(() => {
    let cancelled = false;
    async function initialize() {
      try {
        const [attachmentPage, batchItems] = await Promise.all([
          api.listAttachments(1, 100),
          loadBatches(),
        ]);
        if (cancelled) return;
        setAttachments(attachmentPage.items);
        const current = batchItems[0];
        if (current) selectBatch(current.id);
        for (const batch of batchItems) {
          if (!batch.latest_run_id) continue;
          const run = await api.getRun(batch.latest_run_id);
          if (run.status === 'queued' || run.status === 'running') {
            if (!cancelled) {
              selectBatch(batch.id);
              setActiveRun(run);
            }
            break;
          }
        }
      } catch (cause) {
        if (!cancelled) setError((cause as ApiError).message);
      }
    }
    void initialize();
    return () => {
      cancelled = true;
    };
  }, [api, loadBatches, selectBatch]);

  useEffect(() => {
    if (!selectedBatchId) return;
    let cancelled = false;
    Promise.all([
      api.listTasks({ batch_id: selectedBatchId, page_size: 100 }),
      api.getBatch(selectedBatchId).then(async (batch) => batch.latest_run_id ? api.getRun(batch.latest_run_id) : null),
    ]).then(([result, run]) => {
        if (cancelled) return;
        setTasks([...result.items].sort((a, b) => a.seq - b.seq));
        setActiveRun((current) => current?.status === 'queued' || current?.status === 'running' ? current : run);
      })
      .catch((cause) => {
        if (!cancelled) setError((cause as ApiError).message);
      });
    return () => {
      cancelled = true;
    };
  }, [api, selectedBatchId]);

  const refreshRunResults = useCallback(
    async (batchId: string) => {
      await Promise.all([loadBatches(), ...(batchId === selectedBatchId ? [loadTasks(batchId)] : [])]);
    },
    [loadBatches, loadTasks, selectedBatchId]
  );

  useEffect(() => {
    if (!activeRun || (activeRun.status !== 'queued' && activeRun.status !== 'running')) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const run = await api.getRun(activeRun.id);
        if (cancelled) return;
        setActiveRun(run);
        const finished = run.status !== 'queued' && run.status !== 'running';
        if (finished || run.stage !== activeRun.stage || run.progress.completed !== activeRun.progress.completed) {
          await refreshRunResults(activeRun.batch_id);
        }
        if (finished && run.status === 'succeeded') message.success(runLabel(run));
      } catch (cause) {
        if (!cancelled) {
          setError((cause as ApiError).message);
          setActiveRun({ ...activeRun });
        }
      }
    }, 1200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [activeRun, api, refreshRunResults]);

  const upload = async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      const attachment = await api.uploadAttachment(file);
      setAttachments((current) => [attachment, ...current]);
      setAttachmentIds((current) => [...current, attachment.id]);
    } catch (cause) {
      setError((cause as ApiError).message);
    } finally {
      setUploading(false);
    }
  };

  const startBatch = async (batchId: string) => {
    setGenerating(true);
    try {
      const run = await api.generateBatch(batchId, newIdempotencyKey());
      setActiveRun(run);
      setError(null);
    } finally {
      setGenerating(false);
    }
  };

  const generate = async () => {
    if (!prompt.trim()) return;
    setGenerating(true);
    setError(null);
    try {
      const batch = await api.createBatch(
        {
          goal: prompt.trim(),
          task_count: taskCount,
          task_mode: taskMode,
          reference_text: '',
          attachment_ids: attachmentIds,
        },
        newIdempotencyKey()
      );
      setBatches((current) => [batch, ...current]);
      selectBatch(batch.id);
      setTasks([]);
      await startBatch(batch.id);
      setPrompt('');
    } catch (cause) {
      setError((cause as ApiError).message);
    } finally {
      setGenerating(false);
    }
  };

  const selectedBatch = batches.find((batch) => batch.id === selectedBatchId) ?? null;
  const runActive = activeRun?.status === 'queued' || activeRun?.status === 'running';
  const progress = activeRun
    ? Math.round((activeRun.progress.completed / Math.max(activeRun.progress.total, 1)) * 100)
    : 0;

  const refreshSelected = useCallback(() => {
    if (selectedBatchId) {
      void loadTasks(selectedBatchId);
      void loadBatches();
    }
  }, [loadBatches, loadTasks, selectedBatchId]);

  return (
    <div className="generate-page">
      <section className="prompt-panel">
        <Input.TextArea
          className="prompt-input"
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="告诉 AI 要生成什么任务，例如场景、数量、步骤要求和限制。"
          autoSize={{ minRows: 4, maxRows: 9 }}
          maxLength={10000}
          disabled={generating || runActive}
        />
        <div className="prompt-toolbar">
          <div className="prompt-tools">
            <Upload
              accept=".txt,.md,.csv,.xlsx"
              showUploadList={false}
              beforeUpload={(file) => {
                void upload(file);
                return false;
              }}
              disabled={uploading || runActive}
            >
              <Button loading={uploading}>上传场景库 / 物料库</Button>
            </Upload>
            <Select
              className="attachment-select"
              mode="multiple"
              allowClear
              value={attachmentIds}
              onChange={setAttachmentIds}
              placeholder="选择附件（可选）"
              options={attachments.map((attachment) => ({
                value: attachment.id,
                label: attachment.filename,
              }))}
            />
            <InputNumber
              min={1}
              max={10}
              value={taskCount}
              onChange={(value) => setTaskCount(value ?? 3)}
              addonAfter="条"
              disabled={runActive}
            />
            <Select
              value={taskMode}
              onChange={setTaskMode}
              disabled={runActive}
              options={[
                { value: 'standard', label: '10–20 步' },
                { value: 'long', label: '20–30 步' },
              ]}
            />
          </div>
          <Button
            type="primary"
            size="large"
            onClick={generate}
            loading={generating}
            disabled={!prompt.trim() || runActive}
          >
            生成
          </Button>
        </div>
      </section>

      {error && (
        <Alert
          className="page-alert"
          type="error"
          showIcon
          message={error}
          closable
          onClose={() => setError(null)}
        />
      )}

      {activeRun && activeRun.batch_id === selectedBatchId && (
        <section className="run-panel">
          <div className="run-heading">
            <span>
              {runLabel(activeRun)}
            </span>
            {runActive && <Spin size="small" />}
          </div>
          {runActive && <Progress percent={progress} showInfo={false} />}
          {activeRun.error && <Alert type="error" showIcon message={activeRun.error.message} />}
          {!runActive && activeRun.status !== 'succeeded' && (
            <div className="task-goal">{activeRun.kind !== 'generate_batch'
              ? '任务正文已保留。检查错误后可打开任务重试。'
              : tasks.length === 0
                ? '要求与附件已保留。检查 API 设置后可在当前任务集重新生成。'
                : '已生成的任务已保留。打开失败任务，点击「重新审核」即可继续。'}</div>
          )}
        </section>
      )}

      <div className="collection-workspace">
        <aside className="collection-sidebar">
          <div className="section-heading">任务集</div>
          <div className="collection-list">
            {batches.map((batch) => {
              const total = Object.values(batch.task_counts).reduce((sum, count) => sum + count, 0);
              return (
                <button
                  type="button"
                  key={batch.id}
                  className={`collection-item${batch.id === selectedBatchId ? ' is-active' : ''}`}
                  onClick={() => {
                    if (batch.id !== selectedBatchId) setTasks([]);
                    selectBatch(batch.id);
                  }}
                >
                  <span className="collection-name">{batch.name ?? '未命名任务集'}</span>
                  <span className="collection-meta">
                    {total} 条 · {new Date(batch.created_at).toLocaleDateString()}
                  </span>
                </button>
              );
            })}
            {batches.length === 0 && <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无任务集" />}
          </div>
        </aside>

        <section className="task-panel">
          <div className="task-panel-heading">
            <div>
              <div className="section-heading">{selectedBatch?.name ?? '任务'}</div>
              {selectedBatch && <div className="task-goal">{selectedBatch.goal}</div>}
            </div>
            {selectedBatch?.can_generate && !runActive && (
              <Button loading={generating} onClick={() => startBatch(selectedBatch.id).catch((cause) => setError((cause as ApiError).message))}>
                {selectedBatch.latest_run_id ? '重新生成' : '生成'}
              </Button>
            )}
          </div>
          <div className="task-list">
            {tasks.map((task) => (
              <button
                type="button"
                className="task-row"
                key={task.id}
                onClick={() => setOpenTaskId(task.id)}
              >
                <span className="task-index">{String(task.seq).padStart(2, '0')}</span>
                <span className="task-name">{task.name}</span>
                <span className="task-steps">{task.step_count} 步</span>
                <TaskStatusTag status={task.status} />
              </button>
            ))}
            {tasks.length === 0 && !runActive && (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无任务" />
            )}
          </div>
        </section>
      </div>

      <TaskDrawer
        key={openTaskId ?? 'closed'}
        api={api}
        taskId={openTaskId}
        onClose={() => setOpenTaskId(null)}
        onUpdated={refreshSelected}
        onRunStarted={setActiveRun}
      />
    </div>
  );
}
