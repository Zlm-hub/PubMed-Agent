/**
 * 报告视图（F1–F4 的完整呈现）。
 *
 * 这一部分是**原 App.tsx 的报告逻辑整体搬迁**，渲染结构、接口调用、CSV 导出、
 * 深链 /?q= 行为全部保持原样，未做任何逻辑改动——升级外壳时不碰已验证链路。
 *
 * 新增的唯一能力：injectQuery —— 由对话视图点「查看完整报告」时注入关键词，
 * 复用同一套分析逻辑，避免在对话视图里重复实现一遍报告渲染。
 */
import { useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import EChart from "./EChart";
import WordCloud from "./WordCloud";
import { analyze, AnalyzeResp, TopItem } from "./api";

const BRAND = "#2196F3";
const BASE = "http://localhost:8000";

interface Props {
  /** 外部注入的检索关键词；变化时自动触发一次分析 */
  injectQuery?: string;
  onQueryInjected?: () => void;
}

export default function ReportView({ injectQuery, onQueryInjected }: Props) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<AnalyzeResp | null>(null);
  const [presets, setPresets] = useState<string[]>(["Alzheimer", "CRISPR cancer", "COVID-19 vaccine"]);

  useEffect(() => {
    fetch(`${BASE}/api/demo/presets`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => {
        if (j && Array.isArray(j.presets) && j.presets.length) setPresets(j.presets);
      })
      .catch(() => {});
  }, []);

  // 支持深链：/?q=Alzheimer 打开即自动分析（便于分享与现场演示直接进结果页）
  useEffect(() => {
    const q = new URLSearchParams(window.location.search).get("q");
    if (q && q.trim()) runAnalyze(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 对话视图注入关键词
  useEffect(() => {
    if (injectQuery && injectQuery.trim()) {
      runAnalyze(injectQuery);
      onQueryInjected?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [injectQuery]);

  async function runAnalyze(q: string) {
    const query = q.trim();
    if (!query) return;
    setQuery(query);
    setLoading(true);
    setError("");
    setData(null);
    try {
      const res = await analyze(query, 200);
      if (res.error) setError(res.error);
      else setData(res);
    } catch (e: any) {
      setError(e?.message || "请求失败");
    } finally {
      setLoading(false);
    }
  }

  async function onSearch() {
    await runAnalyze(query);
  }

  const yearOption = useMemo<EChartsOption>(() => {
    const d = data?.stats.year_distribution ?? [];
    return {
      tooltip: { trigger: "axis" },
      grid: { left: 40, right: 16, top: 16, bottom: 28 },
      xAxis: { type: "category", data: d.map((x) => String(x.year)), axisLabel: { color: "#64748b" } },
      yAxis: { type: "value", axisLabel: { color: "#64748b" }, splitLine: { lineStyle: { color: "#eef2f7" } } },
      series: [
        {
          type: "bar",
          data: d.map((x) => x.count),
          itemStyle: { color: BRAND, borderRadius: [4, 4, 0, 0] },
          barWidth: "55%",
        },
      ],
    };
  }, [data]);

  const quartileOption = useMemo<EChartsOption>(() => {
    const d = data?.stats.quartile_distribution ?? [];
    const colorMap: Record<string, string> = {
      Q1: "#16a34a",
      Q2: "#2196F3",
      Q3: "#f59e0b",
      Q4: "#ef4444",
      未知: "#94a3b8",
    };
    return {
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { bottom: 0, textStyle: { color: "#64748b" } },
      series: [
        {
          type: "pie",
          radius: ["45%", "72%"],
          center: ["50%", "44%"],
          label: { show: false },
          data: d.map((x) => ({
            name: x.quartile,
            value: x.count,
            itemStyle: { color: colorMap[x.quartile] ?? "#94a3b8" },
          })),
        },
      ],
    };
  }, [data]);

  const ifs = data?.stats.if_statistics;
  const topJournal = useMemo(() => {
    const t = data?.stats.top100 ?? [];
    return t.find((x) => x.impact_factor) ?? null;
  }, [data]);

  function exportCsv() {
    if (!data) return;
    const rows = data.stats.top100;
    const header = ["排名", "PMID", "标题", "期刊", "年份", "影响因子", "JCR分区", "窗口", "链接"];
    const lines = rows.map((r: TopItem, i) =>
      [i + 1, r.pmid, `"${(r.title || "").replace(/"/g, '""')}"`, r.journal, r.year ?? "", r.impact_factor ?? "", r.quartile ?? "", r.in_recent_5y === false ? "补足" : "近5年", r.url].join(",")
    );
    const csv = "﻿" + [header.join(","), ...lines].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `top100_${(data.query || "pubmed").replace(/\s+/g, "_")}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="w-full max-w-5xl mx-auto px-6 py-8">
      {!data && !loading && (
        <div className="min-h-[58vh] flex flex-col justify-center">
          <div className="text-center mb-8">
            <h1 className="text-2xl md:text-3xl font-semibold leading-snug">
              输入关键词，一键完成 PubMed 文献调研
            </h1>
            <p className="text-sm text-muted mt-3">
              检索 → 统计 → 词云 / 图表 → 影响力 Top100 → 中文综述，全部结论可溯源到 PMID
            </p>
          </div>

          <div className="max-w-3xl mx-auto">
            <div className="flex gap-2">
              <input
                className="flex-1 rounded-lg border border-line bg-white px-4 py-3.5 text-sm outline-none focus:border-brand shadow-sm"
                placeholder="输入关键词，如 CRISPR cancer / Alzheimer / COVID-19 vaccine"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onSearch();
                }}
              />
              <button
                className="rounded-lg bg-brand hover:bg-brand-hover text-white px-7 py-3.5 text-sm font-medium disabled:opacity-50"
                onClick={onSearch}
                disabled={loading}
              >
                分析
              </button>
            </div>

            <div className="flex items-center justify-center gap-2 flex-wrap mt-3">
              <span className="text-xs text-muted">一键演示：</span>
              {presets.map((p) => (
                <button
                  key={p}
                  className="text-xs rounded-full border border-line bg-white px-3 py-1.5 text-muted hover:text-brand hover:border-brand"
                  onClick={() => runAnalyze(p)}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 max-w-4xl mx-auto mt-12">
            <Feature title="F1 统计概览" desc="文献总量、年份分布、期刊分区、影响因子均值/中位/极值" />
            <Feature title="F2 可视化" desc="关键词词云 + MeSH 研究方向标签，纯统计聚类、结果可复现" />
            <Feature title="F3 影响力排序" desc="近 5 年影响因子 Top 100 表格，支持一键导出 CSV" />
            <Feature title="F4 中文综述" desc="基于 Top 摘要生成中文分点综述，每条论断标注 PMID 出处" />
          </div>

          {error && (
            <div className="mt-6 max-w-3xl mx-auto rounded-md border border-red-200 bg-red-50 text-red-600 text-sm px-4 py-3">
              {error}
            </div>
          )}
        </div>
      )}

      {(data || loading) && (
        <div className="space-y-4">
          <div className="flex gap-2">
            <input
              className="flex-1 rounded-md border border-line bg-white px-4 py-3 text-sm outline-none focus:border-brand"
              placeholder="输入关键词，如 CRISPR cancer / Alzheimer / COVID-19 vaccine"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onSearch();
              }}
            />
            <button
              className="rounded-md bg-brand hover:bg-brand-hover text-white px-6 py-3 text-sm font-medium disabled:opacity-50"
              onClick={onSearch}
              disabled={loading}
            >
              {loading ? "分析中…" : "分析"}
            </button>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-muted">一键演示：</span>
            {presets.map((p) => (
              <button
                key={p}
                className="text-xs rounded-full border border-line px-3 py-1.5 text-muted hover:text-brand hover:border-brand disabled:opacity-50"
                onClick={() => runAnalyze(p)}
                disabled={loading}
              >
                {p}
              </button>
            ))}
          </div>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 text-red-600 text-sm px-4 py-3">
              {error}
            </div>
          )}

          {loading && (
            <div className="mt-16 text-center">
              <div className="inline-flex items-center gap-2 text-muted text-sm">
                <span className="h-2 w-2 rounded-full bg-brand animate-pulse" />
                正在检索 PubMed 并分析，请稍候…
              </div>
              <div className="mt-8 grid grid-cols-2 md:grid-cols-4 gap-3">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="h-20 rounded-lg border border-line bg-white animate-pulse" />
                ))}
              </div>
            </div>
          )}

          {data && !loading && (
            <div className="space-y-6">
              <div className="text-sm text-muted">
                检索 “{data.query}” · 共 <b className="text-ink">{data.total.toLocaleString()}</b> 篇 · 本次分析 {data.returned} 篇
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Card label="命中总量" value={data.total.toLocaleString()} />
                <Card
                  label="IF 指标覆盖"
                  value={`${ifs?.known_count ?? 0} 篇`}
                  sub={`覆盖率 ${data.returned ? Math.round(((ifs?.known_count ?? 0) / data.returned) * 100) : 0}% · 其余未收录`}
                />
                <Card label="平均影响因子" value={ifs?.mean != null ? String(ifs.mean) : "—"} sub={ifs?.median != null ? `中位数 ${ifs.median}` : undefined} />
                <Card label="最高 IF 文献" value={topJournal?.impact_factor != null ? String(topJournal.impact_factor) : "—"} sub={topJournal?.journal} />
              </div>

              <section className="rounded-lg border border-line bg-white p-5">
                <h2 className="font-semibold mb-3">中文综述</h2>
                {data.review.mock && (
                  <div className="mb-2 text-xs text-accent">
                    （示例综述：由本次检索的真实统计结果自动生成，未调用大模型；配置 DASHSCOPE_API_KEY 后生成基于摘要原文的 LLM 综述）
                  </div>
                )}
                <div className="text-sm leading-7 whitespace-pre-wrap">{data.review.text}</div>
                {data.review.sources.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-line text-xs text-muted">
                    出处：
                    {data.review.sources.slice(0, 12).map((s) => (
                      <a key={s} className="text-brand hover:underline mr-2" href={`https://pubmed.ncbi.nlm.nih.gov/${s}/`} target="_blank" rel="noreferrer">
                        PMID:{s}
                      </a>
                    ))}
                    {data.review.sources.length > 12 ? `…等 ${data.review.sources.length} 篇` : ""}
                  </div>
                )}
              </section>

              <div className="grid md:grid-cols-2 gap-4">
                <Panel title="年份分布">
                  <EChart option={yearOption} height={280} />
                </Panel>
                <Panel title="期刊分区分布（IF 阈值近似）">
                  <EChart option={quartileOption} height={280} />
                </Panel>
              </div>

              <div className="grid md:grid-cols-2 gap-4">
                <Panel title="关键词词云（字号=词频）">
                  <WordCloud data={data?.stats.wordcloud ?? []} height={340} />
                </Panel>
                <Panel title="研究方向标签">
                  <div className="flex flex-wrap gap-2 pt-2">
                    {(data.stats.topics ?? []).map((t) => (
                      <span key={t.topic} className="inline-flex items-center gap-1 rounded-full bg-brand/10 text-brand text-xs px-3 py-1.5">
                        {t.topic} <span className="text-brand/60">×{t.count}</span>
                      </span>
                    ))}
                    {(data.stats.topics ?? []).length === 0 && <span className="text-sm text-muted">暂无足够 MeSH 数据</span>}
                  </div>
                  <div className="mt-4 pt-3 border-t border-line text-xs text-muted leading-6">
                    按 MeSH 主题词频次自动聚类（纯统计，未调用大模型），已过滤 Humans / Animals / Risk Factors 等无方向区分度的泛化词。
                  </div>
                </Panel>
              </div>

              <section className="rounded-lg border border-line bg-white p-5">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="font-semibold">影响因子 Top {data.stats.top100.length}（近 5 年优先）</h2>
                  <button className="text-xs rounded-md border border-line px-3 py-1.5 text-muted hover:text-brand hover:border-brand" onClick={exportCsv}>
                    导出 CSV
                  </button>
                </div>
                {data.stats.top100_meta && (
                  <div className="mb-2 text-xs text-muted">
                    {data.stats.top100_meta.extended
                      ? `近 ${data.stats.top100_meta.window_years} 年（${data.stats.top100_meta.cutoff_year} 年起）仅 ${data.stats.top100_meta.recent_count} 篇，已按年份就近补足至 100 篇，补足部分标注「补」。`
                      : `${data.stats.top100_meta.cutoff_year} 年以来共 ${data.stats.top100_meta.recent_count} 篇进入近 5 年窗口。`}
                  </div>
                )}
                <div className="overflow-auto max-h-[420px] border border-line rounded-md">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 bg-appbg text-muted">
                      <tr className="text-left">
                        <th className="px-3 py-2 font-medium">#</th>
                        <th className="px-3 py-2 font-medium">标题</th>
                        <th className="px-3 py-2 font-medium">期刊</th>
                        <th className="px-3 py-2 font-medium">年份</th>
                        <th className="px-3 py-2 font-medium">IF</th>
                        <th className="px-3 py-2 font-medium">分区</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.stats.top100.map((r, i) => (
                        <tr key={r.pmid} className="border-t border-line hover:bg-brand/5">
                          <td className="px-3 py-2 text-muted">{i + 1}</td>
                          <td className="px-3 py-2">
                            <a className="hover:text-brand" href={r.url} target="_blank" rel="noreferrer">{r.title || "—"}</a>
                          </td>
                          <td className="px-3 py-2 text-muted">{r.journal || "—"}</td>
                          <td className="px-3 py-2 text-muted">
                            {r.year ?? "—"}
                            {r.in_recent_5y === false && <span className="ml-1 text-[10px] text-accent">补</span>}
                          </td>
                          <td className="px-3 py-2">{r.impact_factor != null ? r.impact_factor : "—"}</td>
                          <td className="px-3 py-2">
                            {r.quartile ? (
                              <span className={`px-2 py-0.5 rounded text-xs ${r.quartile === "Q1" ? "bg-green-100 text-green-700" : r.quartile === "Q2" ? "bg-blue-100 text-blue-700" : r.quartile === "Q3" ? "bg-amber-100 text-amber-700" : "bg-red-100 text-red-700"}`}>{r.quartile}</span>
                            ) : (
                              <span className="text-muted">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <section>
                <h2 className="font-semibold mb-3">相关文献（本次分析 {data.articles.length} 篇）</h2>
                <div className="space-y-3">
                  {data.articles.map((a) => (
                    <a key={a.pmid} href={a.url} target="_blank" rel="noreferrer" className="block rounded-md border border-line bg-white p-4 hover:border-brand transition">
                      <div className="text-sm font-medium leading-6">{a.title}</div>
                      <div className="text-xs text-muted mt-1">
                        {a.journal}
                        {a.year ? ` · ${a.year}` : ""} · PMID:{a.pmid}
                        {a.impact_factor != null ? ` · IF ${a.impact_factor}` : ""}
                      </div>
                    </a>
                  ))}
                </div>
              </section>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className="text-xl font-semibold mt-1">{value}</div>
      {sub && <div className="text-xs text-muted mt-1 truncate">{sub}</div>}
    </div>
  );
}

function Feature({ title, desc }: { title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <div className="text-sm font-medium text-brand">{title}</div>
      <div className="text-xs text-muted mt-1.5 leading-6">{desc}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-white p-5">
      <h2 className="font-semibold mb-2">{title}</h2>
      {children}
    </section>
  );
}
