import { Alert, Button, Input, Pagination, Select, Table, Tag, message } from 'antd';
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ApiClient } from '../api/client';
import { newIdempotencyKey } from '../api/client';
import type { ApiError } from '../api/errors';
import type { Batch, TaskPage, TaskStatus, TaskSummary } from '../api/types';
import { STATUS_LABEL, STATUS_ORDER } from '../api/types';
import TaskDrawer from '../components/TaskDrawer';

interface Props {
  api: ApiClient;
}

export default function ReviewPage({ api }: Props) {
  const [page, setPage] = useState<TaskPage | null>(null);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [status, setStatus] = useState<TaskStatus | 'all'>('all');
  const [batchId, setBatchId] = useState<string | undefined>();
  const [query, setQuery] = useState('');
  const [pageNum, setPageNum] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [openTaskId, setOpenTaskId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    try {
      setPage(await api.listTasks({
        status: status === 'all' ? undefined : status,
        batch_id: batchId,
        q: query || undefined,
        page: pageNum,
        page_size: 20,
      }));
      setError(null);
    } catch (cause) {
      setError((cause as ApiError).message);
    }
  }, [api, batchId, pageNum, query, status]);

  useEffect(() => {
    let cancelled = false;
    api.listTasks({
      status: status === 'all' ? undefined : status,
      batch_id: batchId,
      q: query || undefined,
      page: pageNum,
      page_size: 20,
    })
      .then((result) => {
        if (!cancelled) {
          setPage(result);
          setError(null);
        }
      })
      .catch((cause) => {
        if (!cancelled) setError((cause as ApiError).message);
      });
    return () => {
      cancelled = true;
    };
  }, [api, batchId, pageNum, query, status]);

  useEffect(() => {
    api.listBatches(1, 100).then((result) => setBatches(result.items)).catch(() => {});
  }, [api]);

  const exportSelected = async () => {
    const first = page?.items.find((task) => task.id === selected[0]);
    if (!first || !selected.length) return;
    setExporting(true);
    try {
      const record = await api.createExport(
        { batch_id: first.batch_id, task_ids: selected },
        newIdempotencyKey()
      );
      const blob = await api.downloadExport(record.download_url);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = record.filename;
      link.click();
      URL.revokeObjectURL(url);
      setSelected([]);
      message.success('已导出');
    } catch (cause) {
      message.error((cause as ApiError).message);
    } finally {
      setExporting(false);
    }
  };

  const columns = useMemo(() => [
    { title: '任务', dataIndex: 'name', ellipsis: true },
    {
      title: '任务集',
      dataIndex: 'batch_id',
      width: 210,
      ellipsis: true,
      render: (id: string) => batches.find((batch) => batch.id === id)?.name ?? '未命名任务集',
    },
    { title: '步骤', dataIndex: 'step_count', width: 80 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 120,
      render: (value: TaskStatus) => <Tag>{STATUS_LABEL[value]}</Tag>,
    },
    {
      key: 'action',
      width: 72,
      render: (_: unknown, task: TaskSummary) => (
        <Button type="link" onClick={() => setOpenTaskId(task.id)}>查看</Button>
      ),
    },
  ], [batches]);

  return (
    <div className="review-page">
      {error && <Alert type="error" showIcon message={error} action={<Button onClick={load}>重试</Button>} />}
      <div className="review-toolbar">
        <Select
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPageNum(1);
            setSelected([]);
          }}
          options={[
            { value: 'all', label: '全部状态' },
            ...STATUS_ORDER.map((value) => ({ value, label: STATUS_LABEL[value] })),
          ]}
        />
        <Select
          allowClear
          placeholder="全部任务集"
          value={batchId}
          onChange={(value) => {
            setBatchId(value);
            setPageNum(1);
            setSelected([]);
          }}
          options={batches.map((batch) => ({ value: batch.id, label: batch.name ?? '未命名任务集' }))}
        />
        <Input.Search
          allowClear
          placeholder="搜索任务"
          onSearch={(value) => {
            setQuery(value);
            setPageNum(1);
            setSelected([]);
          }}
        />
        {status === 'approved' && (
          <Button type="primary" disabled={!selected.length} loading={exporting} onClick={exportSelected}>
            导出 XLSX{selected.length ? `（${selected.length}）` : ''}
          </Button>
        )}
      </div>

      <Table
        rowKey="id"
        columns={columns}
        dataSource={page?.items ?? []}
        pagination={false}
        rowSelection={status === 'approved' ? {
          selectedRowKeys: selected,
          onChange: (keys) => setSelected(keys as string[]),
        } : undefined}
        onRow={(task) => ({
          onClick: (event) => {
            if (!(event.target as HTMLElement).closest('button,input,.ant-checkbox')) setOpenTaskId(task.id);
          },
        })}
      />
      <Pagination
        className="review-pagination"
        current={pageNum}
        pageSize={20}
        total={page?.total ?? 0}
        showSizeChanger={false}
        onChange={(value) => {
          setPageNum(value);
          setSelected([]);
        }}
      />

      <TaskDrawer
        key={openTaskId ?? 'closed'}
        api={api}
        taskId={openTaskId}
        onClose={() => {
          setOpenTaskId(null);
          void load();
        }}
        onUpdated={load}
      />
    </div>
  );
}
