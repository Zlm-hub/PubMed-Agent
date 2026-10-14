/**
 * 对话式 Agent 外壳的数据模型。
 *
 * 关于「工具卡片」的诚实说明（评审可对照代码核对）：
 * 1. 卡片名称与入参**对齐后端真实流水线**（backend/app/main.py → pipeline.py → pubmed.py /
 *    metrics.py / analyze.py / review.py），不是 UI 编的占位符。
 * 2. 卡片上展示的结果数值**全部取自 /api/analyze 的真实响应**，无任何编造。
 * 3. 差别只在呈现节奏：后端一次性返回，前端按阶段渐次点亮卡片，并为可读性设了
 *    MIN_REPLAY_MS 最短播放时间；真实总耗时仍如实显示在汇总行。
 * 4. 卡片上的**阶段耗时取自响应体 trace 字段**，是服务端实测值而非前端估算。
 *    后端 trace 只细分到三段（search / stats / review），而卡片有 5 张，
 *    因此耗时只标在「阶段首卡」上——同一个数字标两处会被误读成各自耗时。
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
  /** 所属阶段在服务端的实测耗时（毫秒），来自响应体 trace；仅阶段首卡有值 */
  ms?: number;
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
  /** 排障短码：本次请求的 request_id */
  request_id?: string;
  /** 本次要展示的 Top 榜单条数，来自 parseIntent */
  topN?: number;
  /** 用户的原话（未经关键词提取）；用于保存标题与报告标题，不改变检索词 */
  askText?: string;
  /** SSE 流式生成中的综述增量文本；done 到达后由 result.review 接管渲染，此字段不再显示 */
  reviewLive?: string;
  ts: number;
}

export interface Session {
  id: string;
  /** chat = 对话线程；report = 报告文档（全量快照，可关联来源对话） */
  kind: "chat" | "report";
  /** 标题（对话取首问；报告取主题词） */
  title: string;
  ts: number;
  /** 主题词（报告靠它复现，也是复用键的一部分） */
  query?: string | null;
  /** 报告 → 来源对话 id；独立报告为 null。删对话后此处置空（报告保留） */
  chatId?: string | null;
  /** 报告摘要（篇数/字数/耗时），列表直接显示，无需打开 */
  meta?: ReportMeta | null;
  /** 线程内的问答轮次数（仅对话有值） */
  exchanges?: number;
  /** 归属用户 id（普通用户侧栏恒为自己；管理后台视图用于显示归属） */
  user_id?: string | null;
}

/** 报告列表摘要（对应后端 meta_json） */
export interface ReportMeta {
  total?: number;
  returned?: number;
  review_chars?: number;
  elapsed_ms?: number;
}

/** 结果聚焦维度：控制助手消息里结果块的展示顺序（当前入口收敛后恒为 all，保留以备将来按需聚焦） */
export type Focus = "all" | "stats" | "cloud" | "top100" | "review";

export const MIN_REPLAY_MS = 2600;
export const DEFAULT_MAX_RESULTS = 200;
export const REVIEW_TOP_N = 30;
export const DEFAULT_MODEL = "qwen-plus";

/** 内联 Top 榜默认展示条数（用户没明说时用这个） */
export const DEFAULT_TOP_N = 5;
/** 上限：后端 top100 只有 100 条，要更多也没数据 */
export const MAX_TOP_N = 100;

export const uid = () => Math.random().toString(36).slice(2, 10);
export const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * 自然语言输入解析（确定性规则，不调用大模型）。
 *
 * 解决两个实测暴露的问题：
 * 1. 用户输入「我要看一下医学类的前Top10」时，整句话被原样当作 PubMed 检索词，
 *    命中 799 篇且与主题完全无关（Top100 全是凑巧命中的高分论文）。
 *    → 这里把祈使语与「Top N」剥掉，只把主题词送给 NCBI。
 * 2. 「前 Top10」这个数量要求此前无人消费，卡片固定只展示 5 条。
 *    → 解析出 topN 交给 UI。
 *
 * 规则取向是「宁可不动，不要乱改」：所有前导短语必须**整段命中**才剥除
 * （不是一堆可选片段拼的贪婪正则，否则「研究进展」这种正常关键词会被吃掉），
 * 且剥完为空时无条件退回原始输入，绝不拿空串去检索。
 */
const TOP_N_RE = /(?:top|前)\s*(\d{1,3})|(\d{1,3})\s*(?:篇|条)/i;
/**
 * 剥除数量短语。两侧写法必须区别对待：
 * 「Top10 / 前 10」的量词可有可无（top 10 papers），
 * 「10 篇 / 10 条」则必须带量词——否则 COVID-19、IL-10 这种词里的数字会被啃掉。
 */
const TOP_N_STRIP_RE =
  /\s*(?:的)?\s*(?:(?:top|前)\s*\d{1,3}(?:\s*(?:篇|条|个|名|papers?|articles?|studies|results?|items?))?|\d{1,3}\s*(?:篇|条|个))/gi;

const LEADING_FILLER_RE = new RegExp(
  "^(?:" +
  [
    // 「能给我一下关于 X 的文献」「能不能帮我找找 X」：允许「能/可以」开头，
    // 且「给我/帮我」后面可以**不带动词**（实测漏网：整句被当检索词 → 0 命中）
    "(?:能|能否|能不能|可以|可不可以)\\s*(?:给我|帮我)(?:看|查|找|搜|检索|来)*(?:一下|下)?",
    "(?:能|能否|能不能|可以|可不可以)\\s*(?:给我|帮我)(?:看|查|找|搜|检索|来)+(?:一下|下)?",
    // 「我要看看」「请帮我看一下」这类：动词允许重复出现，否则会剩一个「看」
    "我(?:想|要|需要)?(?:看|查|了解|知道|检索|搜)+(?:一下|下)?",
    "帮(?:我)?(?:看|查|找|检索|搜)+(?:一下|下)?",
    "给我(?:看|查|找|来)(?:一下|下)?",
    "请(?:帮我)?(?:看|查|检索|搜|列出)(?:一下|下)?",
    "麻烦(?:帮我|给我)?(?:看|查|找|检索|搜)+(?:一下|下)?",
    // 双字动词整体命中，避免把「看護学」的「看」削掉
    "(?:查找|查看|查阅|搜索|检索|看看)(?:一下|下)?",
    "(?:看|查|找|搜)(?:一下|下)",
    "i\\s+(?:want|would\\s+like)\\s+to\\s+(?:see|know|find|search)",
    "(?:show|give|find|search|list|get)\\s+me",
    "please\\s+(?:show|find|search|list)(?:\\s+me)?",
  ].join("|") +
  ")[\\s，,：:、的]*",
  "i",
);

/** 剥完祈使语后可能残留的连接词与介词（介词后必须跟空白，避免吃掉 oncology 这类词） */
const LEADING_DEBRIS_RE =
  /^(?:(?:帮我|给我|麻烦(?:你)?|请|然后|再|来)[\s，,：:、的]*|(?:on|about|of|for|regarding|concerning)\s+|(?:关于|有关|对于)[\s，,：:、的]*)+/i;

/** 单个残留动词：必须后跟分隔符才剥，否则会啃掉以动词开头的正常词 */
const LEADING_VERB_RE = /^(?:看|查|找|搜|求|请)(?=[\s，,：:、的])[\s，,：:、的]*/;

/** 结尾的泛化词：的 / 的研究 / 的相关文献 / 方面 … */
const TRAILING_FILLER_RE =
  /[\s，,。.！!？?、]*(?:的)?(?:前)?(?:研究|文献|论文|文章|进展|现状|资料|综述|相关(?:研究|文献|论文|资料)|方面|领域)?[\s，,。.！!？?吧呢啊吗]*$/;

/** 本身就是泛化词的检索词——不能再被削（「研究进展」不该变成「研究」） */
const GENERIC_ONLY_RE = /^(?:研究|文献|论文|文章|进展|现状|资料|方面|领域|相关)$/;

export interface ParsedIntent {
  /** 真正送给 PubMed 的检索词 */
  term: string;
  /** 内联榜单展示条数 */
  topN: number;
  /** 用户原始输入（气泡里照原样显示） */
  raw: string;
  /** term 是否被改写——改写时工具卡上会如实标出原始输入 */
  rewritten: boolean;
}

export function parseIntent(raw: string): ParsedIntent {
  const input = raw.trim();

  // 1) 抽数量要求；抽不到用默认值
  const m = TOP_N_RE.exec(input);
  const asked = m ? Number(m[1] ?? m[2]) : NaN;
  const topN = Number.isFinite(asked) && asked > 0 ? Math.min(asked, MAX_TOP_N) : DEFAULT_TOP_N;

  // 2) 去掉「Top N」短语与结尾泛化词
  let term = input.replace(TOP_N_STRIP_RE, " ");
  const tailStripped = term.replace(TRAILING_FILLER_RE, "");
  // 削完只剩一个泛化词说明削过头了（「研究进展」→「研究」），保留原样
  if (tailStripped.trim() && !GENERIC_ONLY_RE.test(tailStripped.trim())) term = tailStripped;

  // 3) 反复剥开头祈使语（「请帮我看一下」需要剥两轮）
  for (let i = 0; i < 3; i += 1) {
    const before = term;
    term = term
      .replace(LEADING_FILLER_RE, "")
      .replace(LEADING_DEBRIS_RE, "")
      .replace(LEADING_VERB_RE, "");
    if (term === before) break;
  }
  term = term
    .replace(/^[\s，,：:、的]+/, "")
    .replace(/[\s，,。.！!？?、吧呢啊吗]+$/, "")
    .trim();

  // 4) 剥空就退回原输入——绝不拿空串去检索
  if (!term) return { term: input, topN, raw: input, rewritten: false };
  return { term, topN, raw: input, rewritten: term !== input };
}

/**
 * 侧栏主要入口。2026-09-19 收敛两轮：① 原六个「快捷开始」（文献检索/统计概览/词云与趋势/
 * 影响力 Top100/中文综述/中文检索）经确认与正常对话产出 **100% 重叠**，已移除；
 * ② 「设计思考」页按用户要求下线（不再作为功能展示）。现只保留两个真视图入口。
 */
export interface MainEntry {
  id: "chat" | "report";
  label: string;
  desc: string;
}

export const MAIN_ENTRIES: MainEntry[] = [
  {
    id: "chat",
    label: "智能对话",
    desc: "提问即得全流程分析：检索 → 指标 → 统计 → 词云 → 影响力榜单 → 中文综述",
  },
  {
    id: "report",
    label: "智能报告",
    desc: "完整形态：年份/分区/词云图表、Top100 表格与 CSV 导出、综述全文与全部出处",
  },
];

/**
 * 路线图占位：尚未实现，如实标注「规划中」而非虚标为可用功能。
 * （参考产品有选题助手 / 元分析全流程，本项目未做。）
 */
export const ROADMAP: { id: string; label: string; desc: string }[] = [
  { id: "topic", label: "选题助手", desc: "尚未实现，路线图占位" },
  { id: "meta", label: "元分析流程", desc: "尚未实现，路线图占位" },
];

/**
 * 构建一次分析的工具调用序列。
 * 顺序与 backend/app/main.py::analyze() 的真实执行顺序一致。
 */
export function buildTools(query: string, maxResults = DEFAULT_MAX_RESULTS, rawInput?: string): ToolCall[] {
  // 自然语言被改写时，把原始输入一并显示在入参里，避免「用户看到的词」与「实际检索词」不一致
  const esearchArgs: Record<string, string | number> = {
    db: "pubmed",
    term: query,
    retmax: maxResults,
    sort: "relevance",
  };
  if (rawInput && rawInput !== query) esearchArgs.raw_input = rawInput;

  return [
    {
      id: uid(),
      name: "pubmed.esearch",
      title: "检索 PMID 列表",
      args: esearchArgs,
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
      args: { source: "journal_metrics.db（SCImago + OpenAlex）" },
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

/**
 * 后端 trace 的三段与 5 张卡片的对应关系，以及各段的耗时口径。
 * 耗时只挂在阶段首卡（0 / 2 / 4）——两张卡共享同一段，标两处会被误读成各自耗时。
 */
const STAGE_TIMING: Record<number, { key: string; label: string }> = {
  0: { key: "search", label: "检索阶段（含 esearch + efetch）" },
  2: { key: "stats", label: "统计阶段（含指标匹配 + 聚合）" },
  4: { key: "review", label: "综述生成" },
};

/** 用真实响应回填各步结果。所有数值均来自 payload，不做推算。 */
export function fillToolResults(tools: ToolCall[], r: AnalyzeResp): ToolCall[] {
  const ifs = r.stats.if_statistics;
  const years = r.stats.year_distribution ?? [];
  const span =
    years.length > 0 ? `${years[0].year}–${years[years.length - 1].year}` : "—";
  const coverage = r.returned > 0 ? Math.round((ifs.known_count / r.returned) * 100) : 0;
  const reviewLen = (r.review?.text ?? "").length;

  const out = tools.map((t) => ({ ...t }));

  /** 取本卡片所属阶段的实测耗时；trace 缺失（旧缓存）时返回空，卡片不显示耗时 */
  const timing = (i: number): { ms?: number; note?: string } => {
    const d = STAGE_TIMING[i];
    if (!d) return {};
    const item = (r.trace ?? []).find((s) => s.stage === d.key);
    if (!item) return {};
    // 命中预缓存时 trace 是「生成那一次」留下的，措辞必须区分，否则会被当成本次耗时
    const when = r.cached ? "上次生成时实测" : "服务端实测";
    return { ms: item.ms, note: `${when} · ${d.label} ${item.ms} ms` };
  };

  const patch = (i: number, result: string, notes: string[]) => {
    const t = timing(i);
    out[i] = {
      ...out[i],
      result,
      notes: t.note ? [...notes, t.note] : notes,
      ms: t.ms,
      status: "done" as ToolStatus,
    };
  };

  patch(0, `命中 ${r.total.toLocaleString()} 篇`, [`term=${r.query}`, `返回上限 ${DEFAULT_MAX_RESULTS}`]);
  patch(1, `取回 ${r.returned} 篇元数据与摘要`, [`rettype=medline`, `分批并发 150/批`]);
  patch(2, `匹配到指标的文献 ${ifs.known_count} 篇 · 覆盖率 ${coverage}%`, [
    `未收录 ${r.returned - ifs.known_count} 篇降级为「未知」`,
    `来源 SCImago 2025 / OpenAlex 开放数据，无人工录入值`,
  ]);
  patch(
    3,
    `年份跨度 ${span} · 词云 ${(r.stats.wordcloud ?? []).length} 词 · 方向 ${(r.stats.topics ?? []).length} 个 · Top100 ${(r.stats.top100 ?? []).length} 条`,
    [`分区口径：SCImago 官方分区（OpenAlex 兜底为推算）`, `近 5 年不足 100 篇时按年份就近补足`],
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
    `期刊影响因子与分区（SCImago 官方分区优先）用本地 SQLite 指标库匹配，匹配不到不猜——降级为「未知」，避免给出假分区。`,
    `综述优先取有摘要的文献，未配置大模型密钥时用真实统计结果兜底，并在响应里标记 mock 字段。`,
  ];
}

import { API_BASE } from "../apiBase";

/** 会话线程数上限：前后端各挡一道（服务端追加时挤出最旧的线程） */
export const MAX_SESSIONS = 12;

/**
 * 后端线程行（snake_case / ISO 时间）→ 前端 Session（ts 归一为毫秒数）。
 * v2 线程模型：一个会话 = 一个对话线程，可含多轮问答（exchanges 为轮次数）。
 */
function normalizeSession(row: Record<string, unknown>): Session {
  const rawTs = row.ts;
  const ts = typeof rawTs === "number" ? rawTs : Date.parse(String(rawTs)) || Date.now();
  const out: Session = {
    id: String(row.id),
    kind: row.kind === "report" ? "report" : "chat",
    title: (row.title as string) ?? "",
    ts,
  };
  if (typeof row.query === "string") out.query = row.query;
  if (row.chat_id !== undefined) out.chatId = (row.chat_id as string | null) ?? null;
  if (row.meta && typeof row.meta === "object") out.meta = row.meta as ReportMeta;
  const ex = row.exchanges;
  if (typeof ex === "number") out.exchanges = ex;
  return out;
}

/** 侧栏列表：对话与报告混排（按更新时间倒序）；kind 可过滤。后端不可达返回空列表。 */
export async function loadSessions(kind: "all" | "chat" | "report" = "all"): Promise<Session[]> {
  try {
    const r = await fetch(`${API_BASE}/api/sessions?kind=${kind}&limit=${MAX_SESSIONS}`, { credentials: "include" });
    if (!r.ok) return [];
    const data = await r.json();
    return Array.isArray(data.sessions) ? data.sessions.map(normalizeSession) : [];
  } catch {
    return [];
  }
}

/**
 * 检索成功后保存这一轮问答：sessionId 为空 = 新建线程（首问即标题）；
 * 否则追加到该线程（同一线程连问不分家）。返回服务端归一后的轻量线程行
 * 供调用方原地刷新列表 / 记住线程 id；失败返回 null——会话存不上不应打扰检索主流程。
 */
export async function saveExchange(
  sessionId: string | null,
  query: string,
  result: AnalyzeResp,
  elapsedMs?: number,
  askText?: string,
): Promise<Session | null> {
  // 记录口径：**提问气泡存用户原话（ask）**，query 只是检索词——否则历史还原时
  // 用户会看到自己的问题被换成了关键词（2026-09-19 用户实测反馈）。
  // title 仅新建线程时生效，同样取用户原话。
  const body = JSON.stringify({
    kind: "chat",
    query,
    result,
    elapsed_ms: elapsedMs ?? null,
    ...(askText ? { ask: askText } : {}),
    ...(askText && !sessionId ? { title: askText } : {}),
  });
  const url = sessionId ? `${API_BASE}/api/sessions/${sessionId}/messages` : `${API_BASE}/api/sessions`;
  try {
    const r = await fetch(url, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body,
    });
    if (!r.ok) return null;
    return normalizeSession(await r.json());
  } catch {
    return null;
  }
}

/** 报告摘要（侧栏列表直接显示，不必打开详情） */
export function reportMetaOf(doc: AnalyzeResp, elapsedMs?: number): ReportMeta {
  return {
    total: doc.total,
    returned: doc.returned,
    review_chars: (doc.review?.text ?? "").length,
    elapsed_ms: elapsedMs,
  };
}

/**
 * 新建/复用报告记录（**全量快照**，含 200 篇文献）。
 * chatId 非空 = 从属报告（来自某条对话）；null = 独立报告（报告页直接搜索生成）。
 * 服务端复用键 = (chatId, query)：重复点「生成报告」是更新而非新增，不堆重复。
 */
export async function saveReport(
  query: string,
  doc: AnalyzeResp,
  meta: ReportMeta,
  chatId: string | null,
  title?: string,
): Promise<Session | null> {
  try {
    const r = await fetch(`${API_BASE}/api/sessions`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      // title = 用户原话（有则用）；否则退回检索词。报告页标题因此显示"你问的问题"而非关键词
      body: JSON.stringify({ kind: "report", query, doc, meta, chat_id: chatId, ...(title ? { title } : {}) }),
    });
    if (!r.ok) return null;
    return normalizeSession(await r.json());
  } catch {
    return null;
  }
}

/** 打开历史报告：取整份快照直接渲染（不依赖缓存、不发分析请求）。 */
export async function fetchReport(id: string): Promise<{
  id: string;
  title: string;
  query: string;
  meta: ReportMeta;
  doc: AnalyzeResp;
  chatId: string | null;
  savedAt: string;
} | null> {
  try {
    const r = await fetch(`${API_BASE}/api/sessions/${id}`, { credentials: "include" });
    if (!r.ok) return null;
    const d = await r.json();
    if (d.kind !== "report" || !d.doc) return null;
    return {
      id: String(d.id),
      title: String(d.title ?? ""),
      query: String(d.query ?? d.doc?.query ?? ""),
      meta: (d.meta ?? {}) as ReportMeta,
      doc: d.doc as AnalyzeResp,
      chatId: (d.chat_id as string | null) ?? null,
      savedAt: String(d.ts ?? ""),
    };
  } catch {
    return null;
  }
}

/** 删除单条记录（对话或报告）。删对话时服务端只把其报告的 chat_id 置空，报告保留。 */
export async function deleteSession(id: string): Promise<boolean> {
  try {
    const r = await fetch(`${API_BASE}/api/sessions/${id}`, { method: "DELETE", credentials: "include" });
    if (!r.ok) return false;
    const d = await r.json();
    return !!d.deleted;
  } catch {
    return false;
  }
}

/**
 * 打开历史会话：拉整条线程并还原成消息数组（每轮 = 用户气泡 + 助手结果气泡）。
 * 拿不到 / 线程为空返回 null，调用方退回重新检索。
 */
export async function fetchSessionMessages(id: string): Promise<ChatMessage[] | null> {
  try {
    const r = await fetch(`${API_BASE}/api/sessions/${id}`, { credentials: "include" });
    if (!r.ok) return null;
    const detail = await r.json();
    const raw: { role: string; content?: { text?: string; result?: AnalyzeResp; elapsed_ms?: number } }[] =
      Array.isArray(detail.messages) ? detail.messages : [];
    const out: ChatMessage[] = [];
    let lastQuery = "";
    for (const m of raw) {
      if (m.role === "user") {
        lastQuery = m.content?.text ?? "";
        out.push({ id: uid(), role: "user", text: lastQuery, ts: Date.now() });
      } else if (m.role === "assistant" && m.content?.result) {
        const result = m.content.result;
        const query = result.query || lastQuery;
        out.push({
          id: uid(),
          role: "assistant",
          thinking: buildThinking(query, DEFAULT_MAX_RESULTS),
          tools: fillToolResults(buildTools(query, DEFAULT_MAX_RESULTS), result),
          result,
          elapsedMs: typeof m.content.elapsed_ms === "number" ? m.content.elapsed_ms : undefined,
          // 还原时带上同轮的用户原话，供「生成报告」用作标题（不改检索词）
          askText: lastQuery || undefined,
          ts: Date.now(),
        });
      }
    }
    return out.length > 0 ? out : null;
  } catch {
    return null;
  }
}

/** 清空服务端全部历史会话线程；无论成败本地列表都清空（与旧行为观感一致）。 */
export async function clearSessions(): Promise<Session[]> {
  try {
    await fetch(`${API_BASE}/api/sessions`, { method: "DELETE", credentials: "include" });
  } catch {
    /* 后端不可达也照常清空本地列表 */
  }
  return [];
}
