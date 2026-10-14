import { API_BASE as BASE } from "./apiBase";

export interface Article {
  pmid: string;
  title: string;
  journal: string;
  year: number | null;
  url: string;
  mesh?: string[];
  impact_factor?: number | null;
  quartile?: string | null;
}

export interface Review {
  text: string;
  sources: string[];
  mock?: boolean;
}

export interface YearPoint {
  year: number;
  count: number;
}

export interface QuartilePoint {
  quartile: string;
  count: number;
}

export interface IfStats {
  known_count: number;
  mean: number | null;
  median: number | null;
  max: number | null;
  min: number | null;
}

export interface WordItem {
  word: string;
  count: number;
  /** 中文译名（后端补译得到；缺失时前端回退显示英文原词） */
  zh?: string;
}

export interface TopicItem {
  topic: string;
  count: number;
  /** 中文译名（同上） */
  zh?: string;
}

export interface TopItem {
  pmid: string;
  title: string;
  journal: string;
  year: number | null;
  impact_factor: number | null;
  quartile: string | null;
  url: string;
  /** 是否落在"近 5 年"窗口内；false 表示因近 5 年不足 100 篇而就近补足 */
  in_recent_5y?: boolean;
}

export interface Top100Meta {
  window_years: number;
  cutoff_year: number;
  recent_count: number;
  total_count: number;
  extended: boolean;
}

export interface Stats {
  year_distribution: YearPoint[];
  quartile_distribution: QuartilePoint[];
  if_statistics: IfStats;
  wordcloud: WordItem[];
  topics: TopicItem[];
  top100: TopItem[];
  top100_meta?: Top100Meta;
}

export interface TraceStep {
  /** 阶段标识：rewrite / search / stats / review / litlog */
  stage: string;
  /** 中文标签，可直接用于展示 */
  label: string;
  /** 该阶段真实耗时（毫秒） */
  ms: number;
  /** 该阶段是否成功（如没有可用于综述的摘要时为 false） */
  ok: boolean;
  /** 一句话结果摘要，与页面数字同源，可逐条核对 */
  detail: string;
}

/** 中文查询改写信息（渐冻症 → amyotrophic lateral sclerosis） */
export interface RewriteInfo {
  raw: string;
  term: string;
  /** passthrough = 未改写；mapping = 本地映射表；llm = 大模型改写 */
  source: "passthrough" | "mapping" | "llm";
  synonyms?: string[];
}

export interface AnalyzeResp {
  query: string;
  total: number;
  returned: number;
  /** 实际送检的词（含中文改写后的英文术语）；旧缓存可能没有此字段 */
  search_term?: string;
  rewrite?: RewriteInfo;
  stats: Stats;
  articles: Article[];
  review: Review;
  /** 各阶段真实耗时；命中预缓存时是生成当次留下的原始记录 */
  trace?: TraceStep[];
  /** true 表示本次结果直接来自预缓存（后端未重新检索） */
  cached?: boolean;
  /** 0 命中时的英文候选词（前端引导，L2） */
  suggestions?: string[];
  /** 本次请求的排障短码，与后端 logs/ 日志一一对应 */
  request_id?: string;
  error?: string;
}

// API 基址统一由 ./apiBase 提供：生产单端口部署时为空串（同源 /api），
// 本地开发由 frontend/.env.development 注入 http://localhost:8000，行为不变。

export async function analyze(
  query: string,
  maxResults = 200
): Promise<AnalyzeResp> {
  const r = await fetch(`${BASE}/api/analyze`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, max_results: maxResults, include_review: true }),
  });
  if (!r.ok) {
    // 后端把可读原因放在 detail（如「免费试用次数已用完…管理员联系方式：QQ…」），
    // 直接透传比笼统的「请求失败 (403)」有用得多
    let detail = "";
    try {
      const j = (await r.json()) as { detail?: unknown };
      if (typeof j.detail === "string") detail = j.detail;
    } catch {
      /* 非 JSON 响应体，退回状态码文案 */
    }
    throw new Error(detail || `请求失败 (${r.status})`);
  }
  return r.json();
}

/** SSE 阶段事件（字段与后端 /api/analyze/stream 的事件一一对应） */
export interface StageEvent {
  key?: string;
  label?: string;
  status?: "running" | "done" | "error";
  ms?: number;
  detail?: string;
}

/**
 * SSE 流式分析：阶段事件驱动工具卡、综述逐字推送、done 给全量载荷，
 * done 之后还会补发一次 word_zh（词云/主题词中文译名），最后 end 收尾。
 * 返回关闭函数（新请求/卸载时调用，防串流）。
 * 注意：done 之后**不立即关闭**——要等补译；收到 end 或兜底超时才关，
 * 同时用 gotDone 标记避免「服务端正常收流」被误报成「连接中断」。
 */
export function analyzeStream(
  query: string,
  maxResults: number,
  h: {
    onStage: (e: StageEvent) => void;
    onReviewDelta: (text: string) => void;
    onDone: (payload: AnalyzeResp) => void;
    /** 词云/主题词译名（done 之后补发，失败则不会调用） */
    onWordZh?: (map: Record<string, string>) => void;
    onError: (message: string) => void;
  },
): () => void {
  const es = new EventSource(
    `${BASE}/api/analyze/stream?query=${encodeURIComponent(query)}&max_results=${maxResults}&include_review=true`,
    // 携带登录 cookie（同源时默认也带；显式声明防跨源部署漏凭证）
    { withCredentials: true },
  );
  let gotDone = false;
  let closeTimer: number | undefined;

  es.onmessage = (ev) => {
    let d: { type: string; payload?: AnalyzeResp; text?: string; message?: string; map?: Record<string, string> };
    try {
      d = JSON.parse(ev.data);
    } catch {
      return; // 单条坏消息忽略，不中断整条流
    }
    if (d.type === "stage") h.onStage(d as StageEvent);
    else if (d.type === "review_delta") h.onReviewDelta(d.text ?? "");
    else if (d.type === "done" && d.payload) {
      gotDone = true;
      h.onDone(d.payload);
      // 兜底：补译迟迟不来（或后端是旧版本没有 word_zh/end）时，最多再等 15s 就关，避免悬挂连接
      closeTimer = window.setTimeout(() => es.close(), 15000);
    } else if (d.type === "word_zh" && d.map) {
      h.onWordZh?.(d.map);
    } else if (d.type === "end") {
      if (closeTimer) window.clearTimeout(closeTimer);
      es.close();
    } else if (d.type === "error") {
      es.close();
      h.onError(d.message || "流式分析失败");
    }
  };
  es.onerror = () => {
    es.close();
    // 正常收流（服务端关连接）不该被报成错误：只有 done 之前断开才算失败
    if (!gotDone) h.onError("流式连接中断");
  };
  return () => {
    if (closeTimer) window.clearTimeout(closeTimer);
    es.close();
  };
}
