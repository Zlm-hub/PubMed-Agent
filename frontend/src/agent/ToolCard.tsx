/**
 * 单条工具调用卡片。
 *
 * 视觉上还原参考产品的「工具调用块」：一行摘要 + 可展开的入参/结果。
 * 状态四态：pending / running / done / error，全部用 SVG 绘制，不依赖字体图标。
 */
import { useState } from "react";
import type { ToolCall } from "./model";

function StatusMark({ status }: { status: ToolCall["status"] }) {
  if (status === "running") {
    return (
      <span className="relative flex h-4 w-4 items-center justify-center">
        <svg viewBox="0 0 16 16" width="16" height="16" className="animate-spin text-brand">
          <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeOpacity="0.2" strokeWidth="2" />
          <path d="M8 2a6 6 0 0 1 6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </span>
    );
  }
  if (status === "done") {
    return (
      <svg viewBox="0 0 16 16" width="16" height="16" className="text-emerald-500">
        <circle cx="8" cy="8" r="6.5" fill="currentColor" fillOpacity="0.12" />
        <path d="M5 8.2l2.1 2.1L11 6.4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  if (status === "error") {
    return (
      <svg viewBox="0 0 16 16" width="16" height="16" className="text-accent">
        <circle cx="8" cy="8" r="6.5" fill="currentColor" fillOpacity="0.12" />
        <path d="M6 6l4 4M10 6l-4 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" className="text-muted/50">
      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" />
    </svg>
  );
}

const LABEL: Record<ToolCall["status"], string> = {
  pending: "等待中",
  running: "执行中",
  done: "完成",
  error: "失败",
};

export default function ToolCard({ tool }: { tool: ToolCall }) {
  const [open, setOpen] = useState(false);
  const running = tool.status === "running";

  return (
    <div
      className={`rounded-md border bg-white transition-colors ${
        running ? "border-brand/40" : "border-line"
      }`}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left"
      >
        <span className="mt-0.5 shrink-0">
          <StatusMark status={tool.status} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline gap-2">
            <span className="text-sm font-medium text-ink">{tool.title}</span>
            <span className="truncate font-mono text-[11px] text-muted">{tool.name}</span>
          </span>
          {tool.result && <span className="mt-0.5 block text-xs leading-5 text-brand">{tool.result}</span>}
        </span>
        <span className="shrink-0 pt-0.5 text-[11px] text-muted">{LABEL[tool.status]}</span>
      </button>

      {open && (
        <div className="border-t border-line px-3 py-2">
          <div className="text-[11px] font-medium text-muted">入参</div>
          <dl className="mt-1 space-y-0.5">
            {Object.entries(tool.args).map(([k, v]) => (
              <div key={k} className="flex gap-2 font-mono text-[11px] leading-5">
                <dt className="w-20 shrink-0 text-muted">{k}</dt>
                <dd className="min-w-0 break-all text-ink">{String(v)}</dd>
              </div>
            ))}
          </dl>
          {tool.notes && tool.notes.length > 0 && (
            <>
              <div className="mt-2 text-[11px] font-medium text-muted">备注</div>
              <ul className="mt-1 space-y-0.5">
                {tool.notes.map((n) => (
                  <li key={n} className="text-[11px] leading-5 text-muted">
                    · {n}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </div>
  );
}
