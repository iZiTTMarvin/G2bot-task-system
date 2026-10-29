import { Button, Form, Input, Select, message } from 'antd';
import { useEffect, useState } from 'react';
import type { ApiClient } from '../api/client';
import type { ApiError } from '../api/errors';

interface Props {
  api: ApiClient;
}

interface SettingsForm {
  api_format: 'openai' | 'anthropic';
  base_url: string;
  generation_model: string;
  api_key?: string;
}

export default function SettingsPage({ api }: Props) {
  const [form] = Form.useForm<SettingsForm>();
  const [apiKeySet, setApiKeySet] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api
      .getSettings()
      .then((settings) => {
        setApiKeySet(settings.api_key_set);
        form.setFieldsValue({
          api_format: settings.api_format,
          base_url: settings.base_url,
          generation_model: settings.generation_model,
          api_key: '',
        });
      })
      .catch((cause) => message.error((cause as ApiError).message));
  }, [api, form]);

  const save = async (values: SettingsForm) => {
    setSaving(true);
    try {
      const settings = await api.updateSettings({
        api_format: values.api_format,
        base_url: values.base_url,
        generation_model: values.generation_model,
        review_model: values.generation_model,
        ...(values.api_key?.trim() ? { api_key: values.api_key.trim() } : {}),
      });
      setApiKeySet(settings.api_key_set);
      form.setFieldValue('api_key', '');
      message.success('已保存');
    } catch (cause) {
      message.error((cause as ApiError).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="settings-panel">
      <Form form={form} layout="vertical" onFinish={save}>
        <Form.Item name="api_format" label="API 格式" rules={[{ required: true }]}>
          <Select options={[
            { value: 'openai', label: 'OpenAI 兼容 · Chat Completions' },
            { value: 'anthropic', label: 'Anthropic 兼容 · Messages' },
          ]} />
        </Form.Item>
        <Form.Item name="base_url" label="服务地址" extra="支持根地址、带版本或代理前缀的 Base URL，以及所选格式的完整接口地址。" rules={[{ required: true }, { type: 'url' }]}>
          <Input placeholder="https://api.openai.com/v1" />
        </Form.Item>
        <Form.Item name="generation_model" label="模型" rules={[{ required: true }]}>
          <Input placeholder="模型名称" />
        </Form.Item>
        <Form.Item name="api_key" label="API Key">
          <Input.Password
            placeholder={apiKeySet ? '留空保留当前密钥' : '输入 API Key'}
            autoComplete="new-password"
          />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={saving}>
          保存
        </Button>
      </Form>
    </div>
  );
}
