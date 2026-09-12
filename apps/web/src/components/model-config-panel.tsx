"use client";

import { KeyRound, LoaderCircle, Save, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorState, SectionHeader, StatusBadge } from "@/components/ui";
import { fetchRuntimeConfig, updateRuntimeConfig } from "@/lib/api";
import type { ModelKey, RuntimeConfigResponse } from "@/lib/types";

const modelKeys: ModelKey[] = ["deepseek", "chatgpt"];

type ConfigDraft = {
  models: Record<ModelKey, { model: string; base_url: string; api_key: string }>;
  portfolio: RuntimeConfigResponse["portfolio"];
};

function draftFromConfig(config: RuntimeConfigResponse): ConfigDraft {
  return {
    models: {
      deepseek: { model: config.models.deepseek.model, base_url: config.models.deepseek.base_url, api_key: "" },
      chatgpt: { model: config.models.chatgpt.model, base_url: config.models.chatgpt.base_url, api_key: "" },
    },
    portfolio: { ...config.portfolio },
  };
}

export function ModelConfigPanel() {
  const [config, setConfig] = useState<RuntimeConfigResponse | null>(null);
  const [draft, setDraft] = useState<ConfigDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void fetchRuntimeConfig()
      .then((result) => {
        if (!active) return;
        setConfig(result);
        setDraft(draftFromConfig(result));
      })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "模型配置读取失败"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  function updateModel(modelKey: ModelKey, field: "model" | "base_url" | "api_key", value: string) {
    setDraft((current) => current ? {
      ...current,
      models: { ...current.models, [modelKey]: { ...current.models[modelKey], [field]: value } },
    } : current);
  }

  function updatePercent(field: keyof ConfigDraft["portfolio"], value: string) {
    const parsed = Number(value);
    setDraft((current) => current ? { ...current, portfolio: { ...current.portfolio, [field]: Number.isFinite(parsed) ? parsed / 100 : 0 } } : current);
  }

  async function save() {
    if (!draft) return;
    setSaving(true); setError(null); setMessage(null);
    try {
      const result = await updateRuntimeConfig({
        models: Object.fromEntries(modelKeys.map((key) => {
          const model = draft.models[key];
          return [key, { model: model.model, base_url: model.base_url, ...(model.api_key ? { api_key: model.api_key } : {}) }];
        })),
        portfolio: draft.portfolio,
      });
      setConfig(result); setDraft(draftFromConfig(result)); setMessage("配置已应用到当前 API 进程");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模型配置保存失败");
    } finally {
      setSaving(false);
    }
  }

  return <section className="model-config-panel" aria-labelledby="model-config-title">
    <SectionHeader
      className="team-section-heading"
      eyebrow="RUNTIME CONFIG"
      title="模型与下注配置"
      titleId="model-config-title"
      meta={config?.updated_at ? `最近更新 ${formatDate(config.updated_at)}` : "仅当前进程生效"}
    />
    {error && <ErrorState className="error-banner">{error}</ErrorState>}
    {message && <div className="sync-success model-config-success" role="status" aria-live="polite">{message}</div>}
    {loading ? <div className="model-config-loading"><LoaderCircle className="spin" size={16} />正在读取运行配置</div> : draft && config ? <>
      <div className="model-config-models">
        {modelKeys.map((key) => {
          const item = config.models[key];
          const current = draft.models[key];
          return <article className="model-config-card" key={key}>
            <div className="model-config-card-heading">
              <div><Settings2 size={16} aria-hidden="true" /><strong>{item.label}</strong><small>{key}</small></div>
              <StatusBadge variant={!item.enabled ? "partial" : item.provider_ready ? "ready" : "partial"}>{!item.enabled ? "暂时停用" : item.provider_ready ? "可用" : item.api_key_configured ? "配置不完整" : "未配置 Key"}</StatusBadge>
            </div>
            <label><span>模型名称</span><input value={current.model} onChange={(event) => updateModel(key, "model", event.target.value)} /></label>
            <label><span>API 地址</span><input value={current.base_url} onChange={(event) => updateModel(key, "base_url", event.target.value)} /></label>
            <label><span><KeyRound size={12} aria-hidden="true" />API Key <em>{item.api_key_hint ? `当前 ${item.api_key_hint}` : "未配置"}</em></span><input type="password" autoComplete="new-password" value={current.api_key} onChange={(event) => updateModel(key, "api_key", event.target.value)} placeholder="留空保持不变" /></label>
          </article>;
        })}
      </div>
      <div className="model-config-policy">
        <div className="model-config-subheading"><div><span>PAPER PORTFOLIO</span><strong>模拟下注策略</strong></div><small>比例按账户权益计算</small></div>
        <div className="model-config-policy-grid">
          <PercentField label="最小优势" value={draft.portfolio.min_edge} onChange={(value) => updatePercent("min_edge", value)} />
          <PercentField label="最小 EV" value={draft.portfolio.min_ev} onChange={(value) => updatePercent("min_ev", value)} />
          <PercentField label="单笔下注比例" value={draft.portfolio.stake_fraction} onChange={(value) => updatePercent("stake_fraction", value)} />
          <PercentField label="总敞口上限" value={draft.portfolio.max_total_exposure} onChange={(value) => updatePercent("max_total_exposure", value)} />
          <PercentField label="最大回撤" value={draft.portfolio.max_drawdown} onChange={(value) => updatePercent("max_drawdown", value)} />
        </div>
      </div>
      <div className="model-config-actions"><small>API Key 不会回显；留空表示保持当前 Key。重启服务后恢复 .env 配置。</small><button type="button" onClick={() => void save()} disabled={saving}><Save size={15} aria-hidden="true" />{saving ? "应用中" : "应用配置"}</button></div>
    </> : null}
  </section>;
}

function PercentField({ label, value, onChange }: { label: string; value: number; onChange: (value: string) => void }) {
  return <label><span>{label}</span><div className="percent-input"><input type="number" min="0" max="100" step="0.1" value={(value * 100).toFixed(1)} onChange={(event) => onChange(event.target.value)} /><b>%</b></div></label>;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}
