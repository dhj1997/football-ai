"use client";

import type { ReactElement } from "react";
import type { MarketsDetail } from "@/lib/types";

function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function bar(value: number, className: string): ReactElement {
  return (
    <div className="h-1.5 rounded-full bg-slate-800" aria-hidden="true">
      <div className={`h-1.5 rounded-full ${className}`} style={{ width: `${Math.min(100, value * 100)}%` }} />
    </div>
  );
}

export function MarketsDetailPanel({
  marketsDetail,
  currentLine,
}: {
  marketsDetail: MarketsDetail | null | undefined;
  currentLine?: string | null;
}) {
  if (!marketsDetail) {
    return null;
  }
  const lines = Object.entries(marketsDetail.totals_lines);
  const handicaps = Object.entries(marketsDetail.handicap_lines);

  return (
    <div className="space-y-4 text-xs" aria-label="进球与比分维度">
      <p className="text-[11px] text-slate-500">
        以下维度由基线模型的比分概率矩阵确定性派生（同一矩阵，无额外假设）。
      </p>

      <div>
        <b className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          进球数大小盘
        </b>
        <div className="mt-2 overflow-hidden rounded-xl border border-slate-800">
          <div className="grid grid-cols-[4rem_1fr_4.5rem_1fr_4.5rem] gap-2 border-b border-slate-800 bg-pitch-950 px-3 py-2 font-mono text-[11px] text-slate-400">
            <span>盘口</span>
            <span className="text-right">大球</span>
            <span className="text-center">走盘</span>
            <span>小球</span>
            <span />
          </div>
          {lines.map(([line, block]) => (
            <div
              key={line}
              className={`grid grid-cols-[4rem_1fr_4.5rem_1fr_4.5rem] items-center gap-2 border-b border-slate-800/60 px-3 py-2 font-mono tabular-nums text-slate-300 last:border-b-0 ${
                line === "2.5" ? "bg-slate-800/30" : ""
              }`}
            >
              <span className="font-semibold text-slate-200">{line}</span>
              <span className="text-right text-emerald-400">{percent(block.over)}</span>
              <span className="text-center text-slate-500">{block.push > 0 ? percent(block.push) : "—"}</span>
              <span className="text-sky-400">{percent(block.under)}</span>
              <span>{bar(block.over, "bg-emerald-500")}</span>
            </div>
          ))}
        </div>
      </div>

      <div>
        <b className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          双方进球（BTTS）
        </b>
        <div className="mt-2 space-y-1">
          <div className="flex items-center justify-between font-mono tabular-nums text-slate-300">
            <span>是</span>
            <span className="font-bold text-emerald-400">{percent(marketsDetail.btts.yes)}</span>
          </div>
          {bar(marketsDetail.btts.yes, "bg-emerald-500")}
          <div className="flex items-center justify-between font-mono tabular-nums text-slate-300">
            <span>否</span>
            <span className="font-bold text-sky-400">{percent(marketsDetail.btts.no)}</span>
          </div>
          {bar(marketsDetail.btts.no, "bg-sky-500")}
        </div>
      </div>

      <div>
        <b className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
          让球盘多线覆盖概率
        </b>
        <div className="mt-2 overflow-hidden rounded-xl border border-slate-800">
          <div className="grid grid-cols-[4rem_1fr_4.5rem_1fr_4.5rem] gap-2 border-b border-slate-800 bg-pitch-950 px-3 py-2 font-mono text-[11px] text-slate-400">
            <span>盘口</span>
            <span className="text-right">主赢</span>
            <span className="text-center">走盘</span>
            <span>客赢</span>
            <span />
          </div>
          {handicaps.map(([line, block]) => (
            <div
              key={line}
              className={`grid grid-cols-[4rem_1fr_4.5rem_1fr_4.5rem] items-center gap-2 border-b border-slate-800/60 px-3 py-2 font-mono tabular-nums text-slate-300 last:border-b-0 ${
                currentLine && line === currentLine ? "bg-amber-500/10" : ""
              }`}
            >
              <span className="font-semibold text-slate-200">{line}</span>
              <span className="text-right text-amber-400">{percent(block.home_cover)}</span>
              <span className="text-center text-slate-500">{block.push > 0 ? percent(block.push) : "—"}</span>
              <span className="text-sky-400">{percent(block.away_cover)}</span>
              <span>{bar(block.home_cover, "bg-amber-500")}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div>
          <b className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">半场胜平负（近似）</b>
          <div className="mt-2 grid grid-cols-3 gap-2 text-center">
            {(["home", "draw", "away"] as const).map((key) => (
              <div key={key} className="rounded-lg border border-slate-800 bg-pitch-950 px-2 py-1.5">
                <div className="text-[10px] text-slate-500">
                  {key === "home" ? "主" : key === "draw" ? "平" : "客"}
                </div>
                <div className="font-mono text-sm font-bold tabular-nums text-slate-200">
                  {percent(marketsDetail.half_time[key])}
                </div>
              </div>
            ))}
          </div>
        </div>
        <div>
          <b className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">比分概率 Top 6</b>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {marketsDetail.score_matrix_top.map((item) => (
              <span
                key={item.score}
                className="rounded-md border border-slate-800 bg-pitch-950 px-2 py-1 font-mono text-[11px] tabular-nums text-slate-300"
              >
                {item.score} · {percent(item.probability)}
              </span>
            ))}
          </div>
        </div>
      </div>

      <p className="text-[10px] text-slate-600">
        半场维度为 45% xG 独立泊松近似（口径已标注），非独立模型输出。
      </p>
    </div>
  );
}
