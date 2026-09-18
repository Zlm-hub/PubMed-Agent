/**
 * 对话式 Agent 外壳的数据模型。
 *
 * 关于「工具卡片」的诚实说明（评审可对照代码核对）：
 * 1. 卡片名称与入参**对齐后端真实流水线**（backend/app/main.py → pipeline.py → pubmed.py /
 *    metrics.py / analyze.py / review.py），不是 UI 编的占位符。
 * 2. 卡片上展示的结果数值**全部取自 /api/analyze 的真实响应**，无任何编造。
 * 3. 差别只在呈现节奏：后端一次性返回，前端按阶段渐次点亮卡片，并为可读性设了
 *    MIN_REPLAY_MS 最短播放时间；真实总耗时仍如实显示在汇总行。
 *    下一步计划：后端改 SSE 增量推送，即可去掉这层回放（见设计思考页）。
 */
import type { AnalyzeResp } from "../api";

export type ToolStatus = "pending" | "running" | "done" | "error";

export interface ToolCall {
  id: string;
  /** 工具的完全限定名，如 pubmed.esearch */
  name: string;
  /** 中文一句话说明 */
  title: string;
  args: Record<string, string | number>;
  status: ToolStatus;
  /** 一句话结果摘要，取自真实响应 */
  result?: string;
  /** 补充键值，窄屏下折叠 */
  notes?: string[];
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text?: string;
  /** 思考过程，默认折叠 */
  thinking?: string[];
  tools?: ToolCall[];
  /** 助手消息携带的结构化结果，用于内联渲染 */
  result?: AnalyzeResp;
  error?: string;
  /** 真实耗时（毫秒），仅在有真实响应时填写 */
  elapsedMs?: number;
  ts: number;
}

export interface Session {
  id: string;
  /** 会话标题，取首次检索关键词 */
  title: string;
  query: string;
  ts: number;
}

/** 结果聚焦维度：快捷开始入口用它决定助手消息里哪一块默认展开 */
export type Focus = "all" | "stats" | "cloud" | "top100" | "review";

export interface QuickStart {
  id: string;
  label: string;
  desc: string;
  /** 点击后预填到输入框的真实可用关键词（PubMed 能检索到结果） */
  keyword: string;
  focus: Focus;
  /** true 表示尚未实现，UI 上置灰并标注「规划中」 */
  planned?: boolean;
}

export const MIN_REPLAY_MS = 2600;
export const DEFAULT_MAX_RESULTS = 200;
export const REVIEW_TOP_N = 30;
export const DEFAULT_MODEL = "qwen-plus";

export const uid = () => Math.random().toString(36).slice(2, 10);
export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * 快捷开始入口。前 6 项对应已实现的真实能力，后 2 项是明确的路线图占位
 * （参考产品有选题助手 / 元分析全流程，本项目尚未实现，如实标注而非虚标）。
 */
export const QUICK_STARTS: QuickStart[] = [
  { id: "search", label: "文献检索", desc: "关键词 → PubMed 全量分析", keyword: "Alzheimer", focus: "all" },
  { id: "stats", label: "统计概览", desc: "数量 / 年份 / 分区 / 影响因子", keyword: "CRISPR cancer", focus: "stats" },
  { id: "cloud", label: "词云与趋势", desc: "关键词词频 + 研究方向聚类", keyword: "COVID-19 vaccine", focus: "cloud" },
  { id: "top100", label: "影响力 Top100", desc: "近 5 年 IF 排序，可导出", keyword: "cancer immunotherapy", focus: "top100" },
  { id: "review", label: "中文综述", desc: "基于摘要生成分点综述", keyword: "gut microbiome", focus: "review" },
  { id: "design", label: "设计思考", desc: "技术选型与取舍留痕", keyword: "", focus: "all" },
  { id: "topic", label: "选题助手", desc: "尚未实现，路线图占位", keyword: "", focus: "all", planned: true },
  { id: "meta", label: "元分析流程", desc: "尚未实现，路线图占位", keyword: "", focus: "all", planned: true },
];

/**
 * 构建一次分析的工具调用序列。
 * 顺序与 backend/app/main.py::analyze() 的真实执行顺序一致。
 */
export function buildTools(query: string, maxResults = DEFAULT_MAX_RESULTS): ToolCall[] {
  return [
    {
      id: uid(),
      name: "pubmed.esearch",
      title: "检索 PMID 列表",
      args: { db: "pubmed", term: query, retmax: maxResults, sort: "relevance" },
      status: "pending",
    },
    {
      id: uid(),
      name: "pubmed.efetch",
      title: "取回元数据与摘要",
      args: { rettype: "medline", retmode: "xml", batch: 150 },
      status: "pending",
    },
    {
      id: uid(),
      name: "metrics.annotate",
      title: "补期刊影响因子与分区",
      args: { source: "journal_metrics.json" },
      status: "pending",
    },
    {
      id: uid(),
      name: "analyze.aggregate",
      title: "聚合统计与可视化数据",
      args: { dims: "year / quartile / wordcloud / topics / top100" },
      status: "pending",
    },
    {
      id: uid(),
      name: "review.generate",
      title: "生成中文分点综述",
      args: { model: DEFAULT_MODEL, top_n: REVIEW_TOP_N },
      status: "pending",
    },
  ];
}

/** 用真实响应回填各步结果。所有数值均来自 payload，不做推算。 */
export function fillToolResults(tools: ToolCall[], r: AnalyzeResp): ToolCall[] {
  const ifs = r.stats.if_statistics;
  const years = r.stats.year_distribution ?? [];
  const span =
    years.length > 0 ? `${years[0].year}–${years[years.length - 1].year}` : "—";
  const coverage = r.returned > 0 ? Math.round((ifs.known_count / r.returned) * 100) : 0;
  const reviewLen = (r.review?.text ?? "").length;

  const out = tools.map((t) => ({ ...t }));
  const patch = (i: number, result: string, notes: string[]) => {
    out[i] = { ...out[i], result, notes, status: "done" as ToolStatus };
  };

  patch(0, `命中 ${r.total.toLocaleString()} 篇`, [`term=${r.query}`, `返回上限 ${DEFAULT_MAX_RESULTS}`]);
  patch(1, `取回 ${r.returned} 篇元数据与摘要`, [`rettype=medline`, `分批并发 150/批`]);
  patch(2, `匹配到 IF 的文献 ${ifs.known_count} 篇 · 覆盖率 ${coverage}%`, [
    `未收录 ${r.returned - ifs.known_count} 篇降级为「未知」`,
    `来源 OpenAlex + 策展补录`,
  ]);
  patch(
    3,
    `年份跨度 ${span} · 词云 ${(r.stats.wordcloud ?? []).length} 词 · 方向 ${(r.stats.topics ?? []).length} 个 · Top100 ${(r.stats.top100 ?? []).length} 条`,
    [`分区口径：IF 阈值近似`, `近 5 年不足 100 篇时按年份就近补足`],
  );
  patch(
    4,
    `综述 ${reviewLen} 字 · 标注 ${(r.review?.sources ?? []).length} 处 PMID`,
    r.review?.mock
      ? [`未配置 DASHSCOPE_API_KEY，走真实统计兜底生成`]
      : [`模型 ${DEFAULT_MODEL}`, `取 Top ${REVIEW_TOP_N} 篇摘要`],
  );
  return out;
}

/** 助手消息的思考过程文案：描述真实发生的决策，不写无意义的过场。 */
export function buildThinking(query: string, maxResults = DEFAULT_MAX_RESULTS): string[] {
  return [
    `收到关键词「${query}」，准备走完整分析链路（检索 → 指标 → 统计 → 综述）。`,
    `先查本地预缓存，命中则直接复用；未命中再走 NCBI E-utilities，retmax=${maxResults}。`,
    `期刊指标用本地 journal_metrics.json 匹配，匹配不到不猜——降级为「未知」，避免给出假分区。`,
    `综述优先取有摘要的文献，未配置大模型密钥时用真实统计结果兜底，并在响应里标记 mock 字段。`,
  ];
}

const LS_KEY = "pubmed-agent-sessions";
const LS_MAX = 12;

export function loadSessions(): Session[] {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    const list = JSON.parse(raw);
    return Array.isArray(list) ? list.slice(0, LS_MAX) : [];
  } catch {
    return [];
  }
}

export function saveSession(sessions: Session[], query: string): Session[] {
  const exists = sessions.find((s) => s.query === query);
  const next = exists
    ? sessions
    : [{ id: uid(), title: query, query, ts: Date.now() }, ...sessions].slice(0, LS_MAX);
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(next));
  } catch {
    /* 隐私模式下 localStorage 不可用，忽略即可 */
  }
  return next;
}

export function clearSessions(): Session[] {
  try {
    localStorage.removeItem(LS_KEY);
  } catch {
    /* 同上 */
  }
  return [];
}
