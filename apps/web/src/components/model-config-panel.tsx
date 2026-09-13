"use client";

import { KeyRound, Save, Settings2 } from "lucide-react";
import { useEffect, useState } from "react";
import { ErrorState, LoadingState, SectionHeader, StatusBadge } from "@/components/ui";
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

const inputClasses =
  "w-full rounded-xl border border-slate-800 bg-pitch-950 px-3 py-2 font-mono text-xs text-slate-200 outline-none transition-colors placeholder:text-slate-600 focus:border-blue-500";

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

  return <section className="space-y-4" aria-labelledby="model-config-title">
    <SectionHeader
      eyebrow="RUNTIME CONFIG"
      title="模型与下注配置"
      titleId="model-config-title"
      meta={config?.updated_at ? `最近更新 ${formatDate(config.updated_at)}` : "仅当前进程生效"}
    />
    {error && <ErrorState>{error}</ErrorState>}
    {message && (
      <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2.5 text-sm text-emerald-300" role="status" aria-live="polite">
        {message}
      </div>
    )}
    {loading ? <LoadingState>正在读取运行配置</LoadingState> : draft && config ? <>
      <div className="grid gap-4 md:grid-cols-2">
        {modelKeys.map((key) => {
          const item = config.models[key];
          const current = draft.models[key];
          return <article className="rounded-2xl border border-slate-800 bg-pitch-900 p-4 shadow-xl" key={key}>
            <div className="mb-3 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-white">
                <Settings2 size={15} className="text-blue-400" aria-hidden="true" />
                <strong className="text-xs font-bold">{item.label}</strong>
                <small className="font-mono text-[11px] text-slate-500">{key}</small>
              </div>
              <StatusBadge variant={!item.enabled ? "partial" : item.provider_ready ? "ready" : "partial"}>{!item.enabled ? "暂时停用" : item.provider_ready ? "可用" : item.api_key_configured ? "配置不完整" : "未配置 Key"}</StatusBadge>
            </div>
            <div className="space-y-2.5">
              <label className="block"><span className="mb-1 block text-[11px] text-slate-400">模型名称</span><input className={inputClasses} value={current.model} onChange={(event) => updateModel(key, "model", event.target.value)} /></label>
              <label className="block"><span className="mb-1 block text-[11px] text-slate-400">API 地址</span><input className={inputClasses} value={current.base_url} onChange={(event) => updateModel(key, "base_url", event.target.value)} /></label>
              <label className="block">
                <span className="mb-1 flex items-center gap-1 text-[11px] text-slate-400"><KeyRound size={12} aria-hidden="true" />API Key <em className="not-italic text-slate-600">{item.api_key_hint ? `当前 ${item.api_key_hint}` : "未配置"}</em></span>
                <input className={inputClasses} type="password" autoComplete="new-password" value={current.api_key} onChange={(event) => updateModel(key, "api_key", event.target.value)} placeholder="留空保持不变" />
              </label>
            </div>
          </article>;
        })}
      </div>
      <div className="rounded-2xl border border-slate-800 bg-pitch-900 p-4 shadow-xl">
        <div className="mb-3 flex items-end justify-between gap-3">
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider font-mono text-blue-400">PAPER PORTFOLIO</span>
            <strong className="mt-0.5 block text-base font-bold text-white">模拟下注策略</strong>
          </div>
          <small className="text-[11px] text-slate-500">比例按账户权益计算</small>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <PercentField label="最小优势" value={draft.portfolio.min_edge} onChange={(value) => updatePercent("min_edge", value)} />
          <PercentField label="最小 EV" value={draft.portfolio.min_ev} onChange={(value) => updatePercent("min_ev", value)} />
          <PercentField label="单笔下注比例" value={draft.portfolio.stake_fraction} onChange={(value) => updatePercent("stake_fraction", value)} />
          <PercentField label="总敞口上限" value={draft.portfolio.max_total_exposure} onChange={(value) => updatePercent("max_total_exposure", value)} />
          <PercentField label="最大回撤" value={draft.portfolio.max_drawdown} onChange={(value) => updatePercent("max_drawdown", value)} />
        </div>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <small className="text-[11px] text-slate-500">API Key 不会回显；留空表示保持当前 Key。重启服务后恢复 .env 配置。</small>
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white shadow-md shadow-blue-600/30 transition-colors hover:bg-blue-500"
        >
          <Save size={14} aria-hidden="true" />{saving ? "应用中" : "应用配置"}
        </button>
      </div>
    </> : null}
  </section>;
}

function PercentField({ label, value, onChange }: { label: string; value: number; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] text-slate-400">{label}</span>
      <div className="flex items-center rounded-xl border border-slate-800 bg-pitch-950 transition-colors focus-within:border-blue-500">
        <input
          type="number"
          min="0"
          max="100"
          step="0.1"
          value={(value * 100).toFixed(1)}
          onChange={(event) => onChange(event.target.value)}
          className="w-full bg-transparent px-3 py-2 font-mono text-xs tabular-nums text-slate-200 outline-none"
        />
        <b className="pr-3 font-mono text-xs text-slate-500">%</b>
      </div>
    </label>
  );
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(value));
}
