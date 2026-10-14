/**
 * 对话视图：欢迎页 / 消息流 / 输入区，以及工具卡片的推进编排。
 *
 * 推进节奏（v2 SSE 流式）：
 * - 主路径走 /api/analyze/stream：卡片由后端真实阶段事件点亮、综述逐字推送（reviewLive 打字机）；
 * - 后端没有流式端点时自动退回一次性请求 + 固定节奏回放（runLegacy，兜底保可用）；
 * - 卡片上的结果值全部取自真实响应/真实事件，汇总行是真实往返耗时（performance 计时）。
 */
import { useEffect, useRef, useState } from "react";
import { analyze, analyzeStream, AnalyzeResp } from "../api";
import {
  buildThinking,
  buildTools,
  fillToolResults,
  ChatMessage,
  DEFAULT_MAX_RESULTS,
  DEFAULT_TOP_N,
  Focus,
  MIN_REPLAY_MS,
  parseIntent,
  sleep,
  uid,
  type ToolCall,
  type ToolStatus,
} from "./model";
import ToolCard from "./ToolCard";

interface Props {
  draft: string;
  setDraft: (v: string) => void;
  /** 结果聚焦维度（当前恒为 all：六个「快捷开始」入口已移除，聚焦切片不再由入口决定） */
  focus: Focus;
  /** 当前意图标签，显示在输入区上方 */
  intentLabel: string;
  /** 非空时自动执行一次检索；n 递增用于区分相同 query 的重复请求 */
  runRequest: { q: string; n: number } | null;
  /** 非空时整条还原历史线程消息（不重新检索、不播动画）；n 与 runRequest 共用递增序列 */
  restoreRequest: { messages: ChatMessage[]; n: number } | null;
  /** 递增即清空当前对话 */
  resetToken: number;
  mockMode: boolean | null;
  onResult: (r: AnalyzeResp, elapsedMs?: number, askText?: string) => void;
  onGenerateReport: (doc: AnalyzeResp, elapsedMs?: number, askText?: string) => void;
}

export default function ChatPanel({
  draft,
  setDraft,
  focus,
  intentLabel,
  runRequest,
  restoreRequest,
  resetToken,
  mockMode,
  onResult,
  onGenerateReport,
}: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const lastRun = useRef(-1);
  const lastReset = useRef(0);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // 外部触发的检索（侧栏历史回退 / 深链）：先清空当前消息流——
  // 打开某个会话就只看这个会话，不同会话之间互相隔离，也不和手头正聊的内容糊在一起
  useEffect(() => {
    if (runRequest && runRequest.n !== lastRun.current) {
      lastRun.current = runRequest.n;
      setMessages([]);
      void runAgent(runRequest.q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runRequest]);

  // 外部触发的会话回放：整条线程消息一次性还原，不转圈
  const lastRestore = useRef(-1);
  useEffect(() => {
    if (restoreRequest && restoreRequest.n !== lastRestore.current) {
      lastRestore.current = restoreRequest.n;
      restoreSession(restoreRequest.messages);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [restoreRequest]);

  // 外部触发的清空（新对话）
  useEffect(() => {
    if (resetToken !== lastReset.current) {
      lastReset.current = resetToken;
      if (!busyRef.current) setMessages([]);
    }
  }, [resetToken]);

  function patchTool(msgId: string, index: number, status: "pending" | "running" | "done" | "error", payload: AnalyzeResp | null) {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id !== msgId || !m.tools) return m;
        const tools = m.tools.slice();
        const next = { ...tools[index], status };
        if (status === "done" && payload) {
          const filled = fillToolResults(m.tools, payload)[index];
          next.result = filled.result;
          next.notes = filled.notes;
        }
        tools[index] = next;
        return { ...m, tools };
      }),
    );
  }

  async function runAgent(raw: string) {
    // 自然语言输入在这里拆成「检索词 + 展示条数」：
    // 「我要看一下医学类的前Top10」→ term=医学类, topN=10。
    // 之前整句话被原样发给 PubMed，命中结果与主题无关；且条数要求无人消费，卡片固定只出 5 条。
    const intent = parseIntent(raw);
    const query = intent.term;
    if (!query || busyRef.current) return;
    setDraft("");

    // 气泡里显示用户原话；实际检索词显示在工具卡入参中（不一致时额外标 raw_input）
    const userMsg: ChatMessage = { id: uid(), role: "user", text: intent.raw, ts: Date.now() };
    const assistantId = uid();
    const tools = buildTools(query, DEFAULT_MAX_RESULTS, intent.rewritten ? intent.raw : undefined);
    const assistantMsg: ChatMessage = {
      id: assistantId,
      role: "assistant",
      thinking: buildThinking(query, DEFAULT_MAX_RESULTS),
      tools,
      topN: intent.topN,
      askText: intent.raw,
      ts: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setBusy(true);
    busyRef.current = true;

    /** 用户原话：检索用的是提取后的关键词，但保存标题/生成报告要用原话 */
    const askText = intent.raw;

    const t0 = performance.now();

    /** 单张卡片打补丁：状态 + 可选的实时结果/耗时（来自后端真实阶段事件） */
    const setCard = (idx: number, status: ToolStatus, patch?: Partial<ToolCall>) => {
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== assistantId || !m.tools) return m;
          const tl = m.tools.slice();
          tl[idx] = { ...tl[idx], status, ...patch };
          return { ...m, tools: tl };
        }),
      );
    };

    // 流水线阶段 → 工具卡映射：rewrite→卡0；search（esearch+efetch 合并段）→卡0+1；
    // stats→卡2+3；review→卡4。litlog 无对应卡片，忽略。
    const STAGE_CARDS: Record<string, number[]> = { rewrite: [0], search: [0, 1], stats: [2, 3], review: [4] };
    let gotEvent = false;

    const finish = (payload: AnalyzeResp) => {
      // 真实往返耗时（performance 计时），不含任何动画时长
      const elapsedMs = Math.round(performance.now() - t0);
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                tools: fillToolResults(m.tools ?? [], payload),
                result: payload,
                elapsedMs,
                reviewLive: undefined, // 全量结果到达，流式预览交棒给 result.review
              }
            : m,
        ),
      );
      setBusy(false);
      busyRef.current = false;
      onResult(payload, elapsedMs, askText);
    };

    const fail = (msg: string) => {
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? { ...m, error: msg } : m)));
      setBusy(false);
      busyRef.current = false;
    };

    /** 兜底：后端没有流式端点（未重启到新版本）时，退回一次性请求 + 固定节奏回放 */
    const runLegacy = () => {
      const box: { data: AnalyzeResp | null; err: string; ms: number } = { data: null, err: "", ms: 0 };
      const req = analyze(query, DEFAULT_MAX_RESULTS)
        .then((r) => {
          box.ms = performance.now() - t0;
          if (r.error) box.err = r.error;
          else box.data = r;
        })
        .catch((e: unknown) => {
          box.ms = performance.now() - t0;
          box.err = e instanceof Error ? e.message : "请求失败";
        });

      const stepMs = Math.max(300, Math.round(MIN_REPLAY_MS / tools.length));
      void (async () => {
        for (let i = 0; i < tools.length; i += 1) {
          patchTool(assistantId, i, "running", box.data);
          await sleep(stepMs);
          if (i < tools.length - 1) {
            patchTool(assistantId, i, "done", box.data);
          } else {
            // 最后一步必须等真实响应，避免「链路还没跑完就显示完成」
            await req;
            patchTool(assistantId, i, box.err ? "error" : "done", box.data);
          }
        }
        const elapsedMs = Math.round(box.ms);
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== assistantId) return m;
            if (box.err) return { ...m, error: box.err, elapsedMs };
            if (!box.data) return m;
            return { ...m, tools: fillToolResults(m.tools ?? [], box.data), result: box.data, elapsedMs };
          }),
        );
        setBusy(false);
        busyRef.current = false;
        if (box.data) onResult(box.data, elapsedMs, askText);
      })();
    };

    // 主路径：SSE 流式——卡片按后端真实阶段点亮、综述逐字推送，不再用假回放
    analyzeStream(query, DEFAULT_MAX_RESULTS, {
      onStage: (e) => {
        gotEvent = true;
        const map = STAGE_CARDS[e.key ?? ""];
        if (!map) return;
        const status: ToolStatus =
          e.status === "running" ? "running" : e.status === "error" ? "error" : "done";
        for (const idx of map) {
          setCard(idx, status, { ms: e.ms, ...(e.detail ? { result: e.detail } : {}) });
        }
      },
      onReviewDelta: (text) => {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === assistantId ? { ...m, reviewLive: (m.reviewLive ?? "") + text } : m,
          ),
        );
      },
      // done 之后补发的词云/主题词中文译名：原地注入当前这条结果，界面即时切中文
      onWordZh: (map) => {
        setMessages((prev) =>
          prev.map((m) => {
            if (m.id !== assistantId || !m.result) return m;
            const st = m.result.stats;
            return {
              ...m,
              result: {
                ...m.result,
                stats: {
                  ...st,
                  wordcloud: (st.wordcloud ?? []).map((w) =>
                    map[w.word] ? { ...w, zh: map[w.word] } : w,
                  ),
                  topics: (st.topics ?? []).map((t) =>
                    map[t.topic] ? { ...t, zh: map[t.topic] } : t,
                  ),
                },
              },
            };
          }),
        );
      },
      onDone: finish,
      onError: (msg) => {
        if (!gotEvent) {
          // 一个事件都没收到：大概率是后端还没重启到带 /stream 的版本，退回旧链路保可用
          runLegacy();
          return;
        }
        fail(msg);
      },
    });
  }

  /**
   * 历史线程回放：服务端已按轮次组装好完整消息（用户气泡 + 结果气泡），
   * 这里整体替换当前消息流——打开哪个线程就只看哪个线程（会话隔离），点多少次都一份。
   */
  function restoreSession(threadMessages: ChatMessage[]) {
    if (busyRef.current) return; // 正在跑真实检索时不打扰，避免消息流错乱
    setMessages(threadMessages);
  }

  const empty = messages.length === 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {empty ? (
          <Welcome />
        ) : (
          <div className="mx-auto w-full max-w-3xl space-y-5 px-6 py-6">
            {messages.map((m) =>
              m.role === "user" ? (
                <div key={m.id} className="flex justify-end">
                  <div className="max-w-[78%] rounded-lg rounded-br-sm bg-brand px-4 py-2.5 text-sm leading-6 text-white">
                    {m.text}
                  </div>
                </div>
              ) : (
                <AssistantBubble
                  key={m.id}
                  msg={m}
                  active={busy && m.id === messages[messages.length - 1]?.id}
                  focus={focus}
                  onGenerateReport={onGenerateReport}
                  onRetry={(q) => void runAgent(q)}
                />
              ),
            )}
          </div>
        )}
      </div>

      <div className="border-t border-line bg-white px-6 py-3">
        <div className="mx-auto w-full max-w-3xl">
          <div className="flex items-center gap-2 pb-2">
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-appbg px-2.5 py-1 text-[11px] text-muted">
              <span className="h-1.5 w-1.5 rounded-full bg-brand" />
              技能 · 全流程分析
            </span>
            <span className="inline-flex items-center gap-1.5 rounded-full border border-line bg-appbg px-2.5 py-1 text-[11px] text-muted">
              {mockMode === true ? "示例模式（未配置密钥）" : "qwen · DashScope"}
            </span>
            {intentLabel && (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-brand/30 bg-brand/10 px-2.5 py-1 text-[11px] text-brand">
                意图 · {intentLabel}
              </span>
            )}
          </div>

          <div className="flex items-end gap-2">
            <textarea
              ref={inputRef}
              rows={draft.length > 56 ? 3 : 1}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void runAgent(draft);
                }
              }}
              placeholder="输入一个医学关键词，回车开始全流程分析（例：老年痴呆、高血压）…"
              className="max-h-40 min-h-[42px] flex-1 resize-none rounded-lg border border-line bg-white px-4 py-3 text-sm leading-6 outline-none transition-all focus:border-brand focus:ring-2 focus:ring-brand/15"
            />
            <button
              type="button"
              onClick={() => void runAgent(draft)}
              disabled={busy || !draft.trim()}
              className="rounded-lg bg-brand px-5 py-3 text-sm font-medium text-white shadow-card transition-all hover:bg-brand-hover hover:shadow-lift disabled:opacity-40 disabled:shadow-none"
            >
              {busy ? "分析中…" : "发送"}
            </button>
          </div>
          <div className="pt-1.5 text-[11px] leading-5 text-muted">
            Enter 发送 · Shift+Enter 换行 · 检索与统计走 NCBI E-utilities
            与本地期刊指标库，结果可溯源到 PMID；图表 / Top100 表格 / CSV 导出 / 综述全文在「智能报告」
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * 空态欢迎页。原先六张「能力卡」（文献检索/统计概览/词云与趋势/影响力 Top100/中文综述/中文检索）
 * 已移除：它们与正常提问的产出 100% 重叠，只是把预设词填进输入框（见 model.ts 的入口收敛说明）。
 * 空态现在只给一句引导 + 去哪看完整形态，不摆功能入口的架子。
 */
function Welcome() {
  return (
    <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-6 py-10">
      <div className="text-center">
        <div className="mx-auto grid h-14 w-14 place-items-center rounded-xl bg-brand shadow-lift">
          <svg viewBox="0 0 16 16" width="28" height="28" fill="none" stroke="#fff" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M4.5 2.5h4.8l3.2 3.2v7.8h-8V2.5Zm4.8 0v3.2h3.2" />
            <path d="M5.8 9.4h1.3l.9-1.7 1.4 2.8.9-1.1h1.5" />
          </svg>
        </div>
        <h2 className="mt-4 text-[22px] font-semibold leading-8 tracking-tight">你好，我是 PubMed Agent</h2>
        <p className="mt-2 text-sm leading-6 text-muted">
          输入一个关键词，我会跑完「检索 → 指标 → 统计 → 可视化 → 中文综述」整条链路
        </p>
        <p className="mt-4 text-[12px] leading-6 text-muted">
          例：老年痴呆 / 高血压 / 白血病 —— 中文词会自动改写成英文检索词并如实标注
          <br />
          想要年份与分区分布图、Top100 完整表格与 CSV 导出、综述全文？切到「智能报告」
        </p>
      </div>
    </div>
  );
}

function AssistantBubble({
  msg,
  active,
  focus,
  onGenerateReport,
  onRetry,
}: {
  msg: ChatMessage;
  active: boolean;
  focus: Focus;
  onGenerateReport: (doc: AnalyzeResp, elapsedMs?: number, askText?: string) => void;
  onRetry: (q: string) => void;
}) {
  const [manual, setManual] = useState<boolean | null>(null);
  const open = manual ?? active;

  return (
    <div className="flex gap-3">
      <div className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md bg-brand/10 text-[11px] font-medium text-brand">
        AI
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        {msg.thinking && msg.thinking.length > 0 && (
          <div className="rounded-md border border-line bg-appbg">
            <button
              type="button"
              onClick={() => setManual(!open)}
              className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[11px] text-muted transition-colors hover:text-ink"
            >
              <svg viewBox="0 0 16 16" width="11" height="11" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={open ? "rotate-90 transition-transform" : "transition-transform"}>
                <path d="M6 3.5L10.5 8 6 12.5" />
              </svg>
              思考过程
              {active && <span className="ml-1 text-brand">进行中</span>}
            </button>
            {open && (
              <ul className="space-y-1 px-3 pb-2.5">
                {msg.thinking.map((t) => (
                  <li key={t} className="text-[11px] leading-5 text-muted">
                    · {t}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {msg.tools && msg.tools.length > 0 && <div className="space-y-1.5">
          {msg.tools.map((t) => (
            <ToolCard key={t.id} tool={t} />
          ))}
        </div>}

        {/* SSE 流式生成中的综述预览：done 到达后由 result.review 接管，这里即消失 */}
        {msg.reviewLive != null && !msg.result && (
          <div className="rounded-md border border-line bg-white p-3">
            <div className="text-[11px] font-medium text-muted">中文综述 · 流式生成中</div>
            <div className="mt-1.5 whitespace-pre-wrap text-[12px] leading-6 text-ink">
              {msg.reviewLive}
              <span className="ml-0.5 inline-block h-3.5 w-[2px] animate-pulse bg-brand align-middle" aria-hidden="true" />
            </div>
          </div>
        )}

        {msg.error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
            执行失败：{msg.error}
            {msg.request_id && <span className="ml-1 font-mono text-red-500/70">（rid {msg.request_id}）</span>}
          </div>
        )}

        {msg.result && (
          <ResultBlock
            result={msg.result}
            focus={focus}
            elapsedMs={msg.elapsedMs}
            topN={msg.topN}
            askText={msg.askText}
            onGenerateReport={onGenerateReport}
            onRetry={onRetry}
          />
        )}
      </div>
    </div>
  );
}

function ResultBlock({
  result,
  focus,
  elapsedMs,
  topN = DEFAULT_TOP_N,
  askText,
  onGenerateReport,
  onRetry,
}: {
  result: AnalyzeResp;
  focus: Focus;
  elapsedMs?: number;
  /** 内联榜单展示条数，来自本次输入的解析结果 */
  topN?: number;
  /** 用户原话：生成报告时作为标题（检索词仍用关键词） */
  askText?: string;
  onGenerateReport: (doc: AnalyzeResp, elapsedMs?: number, askText?: string) => void;
  /** 0 命中引导：点击候选词重新发起检索 */
  onRetry: (q: string) => void;
}) {
  const [expandReview, setExpandReview] = useState(false);
  const ifs = result.stats.if_statistics;
  const coverage = result.returned > 0 ? Math.round((ifs.known_count / result.returned) * 100) : 0;
  const topJournal = (result.stats.top100 ?? []).find((x) => x.impact_factor) ?? null;
  // 要多少给多少：超出数据量时按实际条数收敛，并在标题里说明原因
  const topList = result.stats.top100 ?? [];
  const shownTopN = Math.min(topN, topList.length);
  const topNShort = topN > topList.length;
  const rewrite = result.rewrite;
  const rewritten = !!rewrite && rewrite.source !== "passthrough" && rewrite.term !== result.query;

  const statsBlock = (
    <div key="stats" className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      <Mini label="命中总量" value={result.total.toLocaleString()} />
      <Mini label="影响因子覆盖" value={`${coverage}%`} sub={`${ifs.known_count} / ${result.returned} 篇`} />
      <Mini label="平均影响因子" value={ifs.mean != null ? String(ifs.mean) : "—"} sub={ifs.median != null ? `中位 ${ifs.median}` : undefined} />
      <Mini label="最高影响因子" value={topJournal?.impact_factor != null ? String(topJournal.impact_factor) : "—"} sub={topJournal?.journal} />
    </div>
  );

  const cloudBlock = (
    <div key="cloud" className="rounded-md border border-line bg-white p-3">
      <div className="text-[11px] font-medium text-muted">
        研究方向（按 MeSH 词频聚类，未调用大模型）
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {(result.stats.topics ?? []).slice(0, 8).map((t) => (
          <span
            key={t.topic}
            title={`${t.topic} · 出现 ${t.count} 次`}
            className="inline-flex items-center gap-1 rounded-full bg-brand/10 px-2.5 py-1 text-[11px] text-brand"
          >
            {t.zh ?? t.topic} <span className="text-brand/60">×{t.count}</span>
          </span>
        ))}
        {(result.stats.topics ?? []).length === 0 && <span className="text-[11px] text-muted">暂无足够 MeSH 数据</span>}
      </div>
      {/* 诚实性：只有真的拿到译名才提「中文为翻译辅助」；没有中文时不说这话 */}
      {(result.stats.topics ?? []).some((t) => t.zh) && (
        <div className="mt-1.5 text-[10px] leading-4 text-muted">
          词条为 PubMed 官方 MeSH 主题词（英文受控词），中文为翻译辅助；悬停可看英文原词。完整词云见「智能报告」。
        </div>
      )}
    </div>
  );

  const topBlock = (
    <div key="top100" className="rounded-md border border-line bg-white">
      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-[11px] font-medium text-muted">
          影响力 Top {shownTopN}（共 {topList.length} 条）
          {topNShort && <span className="ml-1 text-muted">· 你想看 {topN} 条，本次数据只够 {topList.length} 条</span>}
        </span>
        <button type="button" onClick={() => onGenerateReport(result, elapsedMs, askText)} className="text-[11px] text-brand hover:underline">
          查看完整报告
        </button>
      </div>
      <div className="border-t border-line">
        {topList.slice(0, shownTopN).map((r, i) => (
          <div key={r.pmid} className="flex items-start gap-2 border-b border-line px-3 py-2 last:border-b-0">
            <span className="w-4 shrink-0 text-[11px] tabular-nums text-muted">{i + 1}</span>
            <a href={r.url} target="_blank" rel="noreferrer" className="min-w-0 flex-1 truncate text-[12px] leading-5 hover:text-brand">
              {r.title}
            </a>
            <span className="hidden shrink-0 text-[11px] text-muted sm:block">{r.journal}</span>
            <span className="w-14 shrink-0 text-right text-[11px] font-medium tabular-nums">{r.impact_factor ?? "—"}</span>
          </div>
        ))}
      </div>
    </div>
  );

  const text = result.review?.text ?? "";
  const reviewBlock = (
    <div key="review" className="rounded-md border border-line bg-white p-3">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-medium text-muted">中文综述</span>
        {result.review?.mock && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10px] text-amber-700">统计兜底</span>}
        <span className="text-[10px] text-muted">· {text.length} 字 · {result.review?.sources.length ?? 0} 处 PMID 出处</span>
      </div>
      <div className="mt-1.5 whitespace-pre-wrap text-[12px] leading-6 text-ink">
        {expandReview ? text : text.slice(0, 240) + (text.length > 240 ? "…" : "")}
      </div>
      <div className="mt-2 flex items-center gap-3">
        {text.length > 240 && (
          <button type="button" onClick={() => setExpandReview((v) => !v)} className="text-[11px] text-brand hover:underline">
            {expandReview ? "收起" : "展开全文"}
          </button>
        )}
        <button type="button" onClick={() => onGenerateReport(result, elapsedMs, askText)} className="text-[11px] text-muted hover:text-brand">
          生成报告
        </button>
      </div>
    </div>
  );

  const order: Record<Focus, string[]> = {
    // 全流程：四块齐全
    all: ["stats", "cloud", "top100", "review"],
    // 统计概览：只给统计类可视化（榜单与综述各有专门入口，不在这里重复占位）
    stats: ["stats", "cloud"],
    cloud: ["cloud", "stats", "top100", "review"],
    top100: ["top100", "stats", "cloud", "review"],
    review: ["review", "stats", "cloud", "top100"],
  };
  const blocks: Record<string, JSX.Element> = { stats: statsBlock, cloud: cloudBlock, top100: topBlock, review: reviewBlock };
  /** 聚焦后主动收起了部分结果时，如实说明去向，避免被当成「数据没出来」 */
  const trimmed = focus === "stats";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted">
        <span>
          检索 “<span className="text-ink">{result.query}</span>” · 命中 <span className="text-ink">{result.total.toLocaleString()}</span> 篇 · 本次分析 {result.returned} 篇
        </span>
        {rewritten && (
          <span>
            · 实际检索 “<span className="text-ink">{rewrite!.term}</span>”
            （{rewrite!.source === "mapping" ? "本地术语映射" : "大模型改写"}）
          </span>
        )}
        {elapsedMs != null && (
          <span>· {result.cached ? "命中预缓存" : "链路耗时"} {elapsedMs} ms</span>
        )}
        {result.request_id && (
          <span className="font-mono text-muted/60">· rid {result.request_id}</span>
        )}
      </div>

      {result.total === 0 && !(result.suggestions?.length ?? 0) && (
        <div className="rounded-md border border-line bg-appbg px-3 py-2 text-[11px] text-muted">
          未命中文献。可换英文关键词重试；排查时向维护者提供 rid {result.request_id || "—"}。
        </div>
      )}

      {result.total === 0 && (result.suggestions?.length ?? 0) > 0 && (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2.5">
          <div className="text-xs text-amber-800">
            中文词在 PubMed（英文语料库）里匹配不到文献。试试这些英文检索词：
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {result.suggestions!.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onRetry(s)}
                className="rounded-full border border-amber-300 bg-white px-3 py-1 text-[12px] text-amber-900 transition-colors hover:border-amber-500 hover:bg-amber-100"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
      {order[focus].map((k) => blocks[k])}
      {trimmed && (
        <div className="text-[11px] leading-5 text-muted">
          「统计概览」只展示统计类结果 · 完整榜单与中文综述见{" "}
          <button
            type="button"
            onClick={() => onGenerateReport(result, elapsedMs, askText)}
            className="text-brand hover:underline"
          >
            报告页
          </button>
        </div>
      )}
    </div>
  );
}

function Mini({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-md border border-line bg-white px-3 py-2 shadow-card">
      <div className="text-[11px] tracking-wide text-muted">{label}</div>
      <div className="mt-0.5 text-[17px] font-semibold leading-6 tabular-nums">{value}</div>
      {sub && <div className="truncate text-[10px] text-muted">{sub}</div>}
    </div>
  );
}
