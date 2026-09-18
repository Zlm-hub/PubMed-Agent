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
}

export interface TopicItem {
  topic: string;
  count: number;
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

const BASE = "http://localhost:8000";

export async function analyze(
  query: string,
  maxResults = 200
): Promise<AnalyzeResp> {
  const r = await fetch(`${BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, max_results: maxResults, include_review: true }),
  });
  if (!r.ok) {
    throw new Error(`请求失败 (${r.status})`);
  }
  return r.json();
}
