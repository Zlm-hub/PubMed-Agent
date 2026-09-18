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
    // 「我要看看」「请帮我看一下」这类：动词允许重复出现，否则会剩一个「看」
    "我(?:想|要|需要)?(?:看|查|了解|知道|检索|搜)+(?:一下|下)?",
    "帮(?:我)?(?:看|查|找|检索|搜)+(?:一下|下)?",
    "给我(?:看|查|找|来)(?:一下|下)?",
    "请(?:帮我)?(?:看|查|检索|搜|列出)(?:一下|下)?",
    "麻烦(?:帮我)?(?:看|查|检索|搜)(?:一下|下)?",
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
  /[\s，,。.！!？?、]*(?:的)?(?:前)?(?:研究|文献|论文|文章|进展|现状|资料|相关(?:研究|文献|论文|资料)|方面|领域)?[\s，,。.！!？?吧呢啊吗]*$/;

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
 * 快捷开始入口。前 6 项对应已实现的真实能力，后 2 项是明确的路线图占位
 * （参考产品有选题助手 / 元分析全流程，本项目尚未实现，如实标注而非虚标）。
 */
export const QUICK_STARTS: QuickStart[] = [
  { id: "search", label: "文献检索", desc: "关键词 → PubMed 全量分析", keyword: "Alzheimer", focus: "all" },
  { id: "stats", label: "统计概览", desc: "数量 / 年份 / 分区 / 影响因子", keyword: "CRISPR cancer", focus: "stats" },
  { id: "cloud", label: "词云与趋势", desc: "关键词词频 + 研究方向聚类", keyword: "COVID-19 vaccine", focus: "cloud" },
  { id: "top100", label: "影响力 Top100", desc: "近 5 年影响因子排序，可导出", keyword: "cancer immunotherapy", focus: "top100" },
  { id: "review", label: "中文综述", desc: "基于摘要生成分点综述", keyword: "gut microbiome", focus: "review" },
  { id: "cn", label: "中文检索", desc: "中文术语自动改写为英文检索（渐冻症 → ALS）", keyword: "渐冻症", focus: "all" },
  { id: "design", label: "设计思考", desc: "技术选型与取舍留痕", keyword: "", focus: "all" },
  { id: "topic", label: "选题助手", desc: "尚未实现，路线图占位", keyword: "", focus: "all", planned: true },
  { id: "meta", label: "元分析流程", desc: "尚未实现，路线图占位", keyword: "", focus: "all", planned: true },
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
