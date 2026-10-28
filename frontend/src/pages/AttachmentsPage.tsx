// 资料页：上传（TXT/MD/CSV/XLSX）+ 列表 + 解析预览。
import { Button, Card, List, Modal, Space, Tag, Typography, Upload, message } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { InboxOutlined } from '@ant-design/icons';
import type { ApiClient } from '../api/client';
import { ApiError } from '../api/errors';
import type { Attachment, AttachmentSummary } from '../api/types';

interface Props {
  api: ApiClient;
}

export default function AttachmentsPage({ api }: Props) {
  const [items, setItems] = useState<AttachmentSummary[]>([]);
  const [preview, setPreview] = useState<Attachment | null>(null);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api.listAttachments(1, 50);
      setItems(r.items);
    } catch (e) {
      message.error(`${(e as ApiError).message}（列表读取失败）`);
    }
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  const doUpload = async (file: File) => {
    setUploading(true);
    try {
      const att = await api.uploadAttachment(file);
      message.success(`已解析：${att.filename}（${att.text_length} 字）`);
      load();
    } catch (e) {
      message.error(`${(e as ApiError).message}（${(e as ApiError).code}）`);
    } finally {
      setUploading(false);
    }
    return false; // 阻止 antd 默认上传
  };

  return (
    <Card title="参考资料" size="small">
      <Typography.Paragraph type="secondary">
        支持 UTF-8 TXT / MD / CSV / 无宏 XLSX；单文件 ≤ 5 MiB，解析文本 ≤ 50,000 字符，CSV/XLSX ≤ 20,000
        单元格；XLSX 公式单元格会被拒绝。文件内容仅作为资料，不会被当作指令执行。
      </Typography.Paragraph>
      <Upload.Dragger
        accept=".txt,.md,.csv,.xlsx"
        showUploadList={false}
        customRequest={({ file }) => doUpload(file as File)}
        disabled={uploading}
      >
        <p className="ant-upload-drag-icon"><InboxOutlined /></p>
        <p className="ant-upload-text">点击或拖拽文件上传</p>
        <p className="ant-upload-hint">上传后立即解析并生成预览</p>
      </Upload.Dragger>

      <List
        style={{ marginTop: 16 }}
        size="small"
        header={<span>已上传 {items.length} 个附件</span>}
        dataSource={items}
        locale={{ emptyText: '暂无附件；生成批次时可直接粘贴文本资料' }}
        renderItem={(a) => (
          <List.Item
            actions={[
              <Button
                key="preview"
                size="small"
                type="link"
                onClick={async () => {
                  try {
                    setPreview(await api.getAttachment(a.id));
                  } catch (e) {
                    message.error((e as ApiError).message);
                  }
                }}
              >
                解析预览
              </Button>,
            ]}
          >
            <Space wrap>
              <span>{a.filename}</span>
              <Tag>{a.media_type}</Tag>
              <Tag>{(a.size_bytes / 1024).toFixed(1)} KB</Tag>
              <Tag color="blue">{a.text_length} 字</Tag>
              <span style={{ color: '#888' }}>{new Date(a.created_at).toLocaleString()}</span>
            </Space>
          </List.Item>
        )}
      />

      <Modal
        open={!!preview}
        title={preview ? `解析预览：${preview.filename}` : ''}
        footer={null}
        onCancel={() => setPreview(null)}
        width={720}
      >
        <pre
          data-testid="parsed-text"
          style={{
            maxHeight: 420,
            overflow: 'auto',
            whiteSpace: 'pre-wrap',
            background: '#fafafa',
            padding: 12,
            borderRadius: 6,
            fontSize: 12,
          }}
        >
          {preview?.parsed_text}
        </pre>
      </Modal>
    </Card>
  );
}
