// 设置页：模型配置；密钥只写不回显。
import { Alert, Button, Card, Form, Input, Space, Tag, Typography, message } from 'antd';
import { useEffect, useState } from 'react';
import type { ApiClient } from '../api/client';
import { ApiError } from '../api/errors';
import type { Settings } from '../api/types';

interface Props {
  api: ApiClient;
}

export default function SettingsPage({ api }: Props) {
  const [form] = Form.useForm();
  const [current, setCurrent] = useState<Settings | null>(null);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const s = await api.getSettings();
      setCurrent(s);
      form.setFieldsValue({ base_url: s.base_url, generation_model: s.generation_model, review_model: s.review_model, api_key: '' });
    } catch (e) {
      message.error((e as ApiError).message);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  const onSave = async (values: { base_url: string; generation_model: string; review_model: string; api_key?: string }) => {
    setSaving(true);
    try {
      const payload: { base_url: string; generation_model: string; review_model: string; api_key?: string } = {
        base_url: values.base_url,
        generation_model: values.generation_model,
        review_model: values.review_model,
      };
      // 空白表示保留原密钥，不提交 api_key 字段；掩码不回填
      if (values.api_key && values.api_key.trim()) payload.api_key = values.api_key.trim();
      const s = await api.updateSettings(payload);
      setCurrent(s);
      form.setFieldValue('api_key', '');
      message.success('配置已保存（未做真实连通性调用）');
    } catch (e) {
      message.error(`${(e as ApiError).message}（${(e as ApiError).code}）`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="模型设置" size="small" style={{ maxWidth: 640 }}>
      <Typography.Paragraph type="secondary">
        OpenAI 兼容地址与密钥；生成与审核共用同一 endpoint。保存只验证格式，不发收费请求。密钥保存在本地
        data 目录，接口只回「已设置」状态，不会回显。
      </Typography.Paragraph>
      {current && (
        <Space style={{ marginBottom: 16 }}>
          <Tag color={current.api_key_set ? 'green' : 'red'}>
            {current.api_key_set ? 'API Key 已设置' : 'API Key 未设置'}
          </Tag>
        </Space>
      )}
      <Form form={form} layout="vertical" onFinish={onSave}>
        <Form.Item
          name="base_url"
          label="Base URL（OpenAI 兼容）"
          rules={[{ required: true }, { type: 'url', message: '必须是 http/https 地址' }]}
        >
          <Input placeholder="https://api.example.com/v1" />
        </Form.Item>
        <Form.Item name="generation_model" label="生成模型" rules={[{ required: true }]}>
          <Input placeholder="如 glm-4.7 / gpt-4o / deepseek-chat" />
        </Form.Item>
        <Form.Item name="review_model" label="审核模型" rules={[{ required: true }]}>
          <Input placeholder="可与生成模型相同" />
        </Form.Item>
        <Form.Item
          name="api_key"
          label="API Key（留空表示保留原密钥）"
          extra="本地保存，不回显；两个模型共用。"
        >
          <Input.Password placeholder={current?.api_key_set ? '已设置（留空保留）' : '未设置'} autoComplete="new-password" />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>
          保存配置
        </Button>
      </Form>
      <Alert
        style={{ marginTop: 16 }}
        type="info"
        showIcon
        message="活动作业运行期间不允许修改配置"
        description="避免作业中途更换模型导致含义不清；请等作业结束后再保存。"
      />
    </Card>
  );
}
