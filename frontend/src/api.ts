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

export interface AnalyzeResp {
  query: string;
  total: number;
  returned: number;
  stats: Stats;
  articles: Article[];
  review: Review;
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
