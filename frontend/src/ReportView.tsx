/**
 * 报告视图（F1–F4 的完整呈现）。
 *
 * 这一部分是**原 App.tsx 的报告逻辑整体搬迁**，渲染结构、接口调用、CSV 导出、
 * 深链 /?q= 行为全部保持原样，未做任何逻辑改动——升级外壳时不碰已验证链路。
 *
 * 新增的唯一能力：injectQuery —— 由对话视图点「查看完整报告」时注入关键词，
 * 复用同一套分析逻辑，避免在对话视图里重复实现一遍报告渲染。
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import EChart from "./EChart";
import WordCloud from "./WordCloud";
import { analyze, AnalyzeResp, TopItem } from "./api";
import CitationText from "./CitationText";
import Pager from "./Pager";
import { reportMetaOf, saveReport, type Session } from "./agent/model";
import { Icon } from "./agent/Sidebar";
import { API_BASE as BASE } from "./apiBase";

const BRAND = "#2196F3";

/**
 * 分区的中文注释：客户看不懂 Q1/Q2 的英文缩写，图例、悬浮提示、表格徽标一律附带中文。
 * 口径说明（与后端一致）：Q1 = 该领域影响因子前 25%，Q2 = 25–50%，Q3 = 50–75%，
 * Q4 = 后 25%；「未匹配」= 该期刊不在本地指标库中，如实标注而非猜测。
 */
const QUARTILE_CN: Record<string, string> = {
  Q1: "一区",
  Q2: "二区",
  Q3: "三区",
  Q4: "四区",
  未知: "未匹配",
};
const quartileLabel = (q: string) => (QUARTILE_CN[q] ? `${q} ${QUARTILE_CN[q]}` : q);

interface Props {
  /** 外部注入的检索关键词；变化时自动触发一次分析 */
  injectQuery?: string;
  onQueryInjected?: () => void;
  /**
   * 外部注入的整份历史报告快照：非空时**直接渲染这份快照**（不再请求分析）。
   * 对应侧栏「历史会话」里 kind=report 的条目。
   */
  injectSnapshot?: {
    title: string;
    query: string;
    doc: AnalyzeResp;
    meta: { total?: number; returned?: number; review_chars?: number; elapsed_ms?: number };
    chatId: string | null;
    chatTitle?: string;
    savedAt: string;
  } | null;
  /** 「来自对话：xxx →」跳回来源对话线程 */
  onNavigateToChat?: (chatId: string) => void;
  /** 本次检索产生的独立报告已落库：通知外壳把侧栏刷新并高亮它 */
  onReportSaved?: (row: Session) => void;
  /** 递增即清空当前报告、回到「新建报告」起始页（侧栏「智能报告」入口用，语义对齐「新对话」） */
  clearToken?: number;
}

export default function ReportView({ injectQuery, onQueryInjected, injectSnapshot, onNavigateToChat, onReportSaved, clearToken }: Props) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [data, setData] = useState<AnalyzeResp | null>(null);
  /** 非空表示当前展示的是历史快照（页面标注时间与来源对话） */
  const [snapshotMeta, setSnapshotMeta] = useState<{
    savedAt: string;
    chatId: string | null;
    chatTitle?: string;
    /** 报告标题（用户原话）与检索词；两者不同时横幅上补「提问：…」 */
    title?: string;
    query?: string;
  } | null>(null);
  const [presets, setPresets] = useState<string[]>(["阿尔茨海默病", "肺癌", "高血压", "渐冻症"]);
  /** 相关文献列表分页：页大小可选 5/10/15/20，换页大小回到第 1 页 */
  const [artPage, setArtPage] = useState(1);
  const [artPageSize, setArtPageSize] = useState(10);
  const artTopRef = useRef<HTMLDivElement | null>(null);

  /** 翻页后把列表顶部滚回视野（200 篇时底部翻页不滚回会看不到新内容） */
  function goArtPage(p: number) {
    setArtPage(p);
    artTopRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  useEffect(() => {
    fetch(`${BASE}/api/demo/presets`, { credentials: "include" })
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

  // 外部注入关键词（对话里点「生成报告」/ 工作目录跳转）：跑一次分析
  useEffect(() => {
    if (injectQuery && injectQuery.trim()) {
      runAnalyze(injectQuery);
      onQueryInjected?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [injectQuery]);

  // 外部注入整份历史报告快照：直接渲染，不发分析请求（离线也能看）
  useEffect(() => {
    if (!injectSnapshot) return;
    setSnapshotMeta({
      savedAt: injectSnapshot.savedAt,
      chatId: injectSnapshot.chatId,
      chatTitle: injectSnapshot.chatTitle,
      title: injectSnapshot.title,
      query: injectSnapshot.query,
    });
    setQuery(injectSnapshot.query);
    setError("");
    setLoading(false);
    setData(injectSnapshot.doc);
  }, [injectSnapshot]);

  // 侧栏「智能报告」入口：清空当前报告，回到「新建报告」起始页（对齐「新对话」的语义）
  useEffect(() => {
    if (!clearToken) return;
    setQuery("");
    setData(null);
    setError("");
    setLoading(false);
    setSnapshotMeta(null);
    setArtPage(1);
  }, [clearToken]);

  async function runAnalyze(q: string) {
    const query = q.trim();
    if (!query) return;
    const t0 = performance.now();
    setSnapshotMeta(null); // 主动查询 = 实时分析，不再标注为历史快照
    setQuery(query);
    setLoading(true);
    setError("");
    setData(null);
    setArtPage(1); // 新一次分析从第 1 页开始，避免停在上一次的页码上
    try {
      const res = await analyze(query, 200);
      if (res.error) setError(res.error);
      else {
        setData(res);
        // 报告页直接检索产生的记录进历史（独立报告：无来源对话）。
        // 失败静默——存不上不影响看报告（与对话侧同款 best-effort）。
        void saveReport(res.query, res, reportMetaOf(res, Math.round(performance.now() - t0)), null).then(
          (row) => {
            if (row) onReportSaved?.(row); // 让侧栏立即出现并高亮这条报告
          },
        );
      }
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
      tooltip: {
        trigger: "item",
        // 悬浮也带中文注释，避免只看图例时对不上（参数类型按 ECharts 的实际回调形状收敛）
        formatter: (p: unknown) => {
          const it = p as { name?: string; value?: unknown; percent?: number };
          return `${quartileLabel(String(it.name ?? ""))}: ${it.value} 篇 (${it.percent}%)`;
        },
      },
      legend: {
        bottom: 0,
        textStyle: { color: "#64748b" },
        formatter: (name: string) => quartileLabel(name),
      },
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
    const header = ["排名", "PMID", "标题", "期刊", "年份", "影响因子", "分区", "窗口", "链接"];
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

  // 相关文献分页切片（页码越界时自动收敛到最后一页，避免换页大小后出现空白页）
  const artTotal = data?.articles.length ?? 0;
  const artPages = Math.max(1, Math.ceil(artTotal / artPageSize));
  const artPageClamped = Math.min(artPage, artPages);
  const artSlice = (data?.articles ?? []).slice(
    (artPageClamped - 1) * artPageSize,
    artPageClamped * artPageSize,
  );

  return (
    <div className="w-full max-w-5xl mx-auto px-6 py-8">
      {!data && !loading && (
        <div className="min-h-[58vh] flex flex-col justify-center">
          <div className="text-center mb-8">
            <h1 className="text-[26px] md:text-3xl font-semibold leading-snug tracking-tight">
              输入关键词，一键完成 PubMed 文献调研
            </h1>
            <p className="text-sm text-muted mt-3">
              检索 → 统计 → 词云 / 图表 → 影响力 Top100 → 中文综述，全部结论可溯源到 PMID
            </p>
          </div>

          <div className="max-w-3xl mx-auto">
            <div className="flex gap-2">
              <input
                className="flex-1 rounded-lg border border-line bg-white px-4 py-3.5 text-sm outline-none transition-all focus:border-brand focus:ring-2 focus:ring-brand/15 shadow-card"
                placeholder="输入关键词，如 阿尔茨海默病 / 肺癌 / 高血压"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onSearch();
                }}
              />
              <button
                className="rounded-lg bg-brand hover:bg-brand-hover text-white px-7 py-3.5 text-sm font-medium shadow-card transition-all hover:shadow-lift disabled:opacity-50 disabled:shadow-none"
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
            <Feature icon="stats" title="统计概览" desc="文献总量、年份分布、期刊分区、影响因子均值/中位/极值" />
            <Feature icon="cloud" title="可视化" desc="关键词词云 + MeSH 研究方向标签，纯统计聚类、结果可复现" />
            <Feature icon="top100" title="影响力排序" desc="近 5 年影响因子 Top 100 表格，支持一键导出 CSV" />
            <Feature icon="review" title="中文综述" desc="基于 Top 摘要生成中文分点综述，每条论断标注 PMID 出处" />
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
              className="flex-1 rounded-md border border-line bg-white px-4 py-3 text-sm outline-none transition-all focus:border-brand focus:ring-2 focus:ring-brand/15"
              placeholder="输入关键词，如 阿尔茨海默病 / 肺癌 / 高血压"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onSearch();
              }}
            />
            <button
              className="rounded-md bg-brand hover:bg-brand-hover text-white px-6 py-3 text-sm font-medium shadow-card transition-all hover:shadow-lift disabled:opacity-50 disabled:shadow-none"
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

          {/* 历史报告：整份快照直接渲染（不重新分析）；标注快照时间与来源对话 */}
          {snapshotMeta && data && !loading && (
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-line bg-appbg px-4 py-2.5 text-xs text-muted">
              <span>
                历史报告快照 · 生成于{" "}
                {snapshotMeta.savedAt ? new Date(snapshotMeta.savedAt).toLocaleString() : "—"}
              </span>
              <span className="text-muted/70">（快照为生成那一刻的数据，不是实时结果）</span>
              {/* 提问原话与检索词不同时，把原话也标出来——检索用关键词，但问题不能被改写 */}
              {snapshotMeta.title && snapshotMeta.title !== snapshotMeta.query && (
                <span className="min-w-0 truncate">提问：{snapshotMeta.title}</span>
              )}
              {snapshotMeta.chatId && (
                <button
                  type="button"
                  onClick={() => snapshotMeta.chatId && onNavigateToChat?.(snapshotMeta.chatId)}
                  className="text-brand transition-colors hover:underline"
                >
                  来自对话：{snapshotMeta.chatTitle || "查看该对话"} →
                </button>
              )}
            </div>
          )}

          {data && !loading && data.total === 0 && (
            <div className="rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              「{data.query}」在 PubMed（英文语料库）中未命中文献。
              {data.suggestions && data.suggestions.length > 0 && (
                <>
                  {" "}试试这些英文检索词：
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {data.suggestions.map((sg) => (
                      <button
                        key={sg}
                        className="rounded-full border border-amber-300 bg-white px-3 py-1 text-xs text-amber-900 hover:border-amber-500"
                        onClick={() => runAnalyze(sg)}
                      >
                        {sg}
                      </button>
                    ))}
                  </div>
                </>
              )}
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
                  label="影响因子覆盖"
                  value={`${ifs?.known_count ?? 0} 篇`}
                  sub={`覆盖率 ${data.returned ? Math.round(((ifs?.known_count ?? 0) / data.returned) * 100) : 0}% · 其余未收录`}
                />
                <Card label="平均影响因子" value={ifs?.mean != null ? String(ifs.mean) : "—"} sub={ifs?.median != null ? `中位数 ${ifs.median}` : undefined} />
                <Card label="最高影响因子文献" value={topJournal?.impact_factor != null ? String(topJournal.impact_factor) : "—"} sub={topJournal?.journal} />
              </div>
              <div className="text-xs text-muted leading-6">
                数据来源：影响因子与分区来自 SCImago 2025 / OpenAlex 开放数据（近 2 年窗口），分区为 SCImago 官方发布（OpenAlex 兜底条目为推算），数值与 JCR 官方口径存在差异，仅供参考。
              </div>

              <section className="rounded-lg border border-line bg-white p-5 shadow-card">
                <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold">
                  <span className="h-3.5 w-1 rounded-full bg-brand" aria-hidden="true" />
                  中文综述
                </h2>
                {data.review.mock && (
                  <div className="mb-2 text-xs text-accent">
                    （示例综述：由本次检索的真实统计结果自动生成，未调用大模型；配置 DASHSCOPE_API_KEY 后生成基于摘要原文的 LLM 综述）
                  </div>
                )}
                {/* 正文里的 [PMID: xxx] 解析成可点击链接（悬停显示该文献真实标题/期刊/年份） */}
                <div className="text-sm leading-7 whitespace-pre-wrap">
                  <CitationText text={data.review.text} articles={data.articles ?? []} />
                </div>
                {data.review.sources.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-line">
                    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-xs text-muted">
                      <span>文献出处</span>
                      <span className="tabular-nums">
                        共 {data.review.sources.length} 篇 · 按正文引用顺序 · 点击跳转 PubMed
                      </span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {data.review.sources.map((s) => {
                        // 悬停给出该 PMID 的真实标题/期刊/年份（取自同一次响应，不做推测）
                        const art = (data.articles ?? []).find((a) => a.pmid === s);
                        const tip = art
                          ? `${art.title}${art.journal ? ` · ${art.journal}` : ""}${art.year ? ` · ${art.year}` : ""}`
                          : `PubMed PMID ${s}`;
                        return (
                          <a
                            key={s}
                            href={`https://pubmed.ncbi.nlm.nih.gov/${s}/`}
                            target="_blank"
                            rel="noreferrer"
                            title={tip}
                            className="rounded-full border border-line bg-appbg px-2 py-0.5 text-[11px] tabular-nums text-muted transition-colors hover:border-brand hover:text-brand"
                          >
                            {s}
                          </a>
                        );
                      })}
                    </div>
                  </div>
                )}
              </section>

              <div className="grid md:grid-cols-2 gap-4">
                <Panel title="年份分布">
                  <EChart option={yearOption} height={280} />
                </Panel>
                <Panel title="期刊分区分布（SCImago 官方分区 / OpenAlex 推算兜底）">
                  <EChart option={quartileOption} height={280} />
                  {/* 图下补口径说明：客户看不懂 Q1–Q4 缩写 */}
                  <div className="mt-2 text-[11px] leading-5 text-muted">
                    分区口径：Q1 一区＝该领域影响因子前 25%，Q2 二区＝25–50%，Q3 三区＝50–75%，
                    Q4 四区＝后 25%；「未匹配」＝该期刊未收录于本地指标库，如实标注、不做推测。
                  </div>
                </Panel>
              </div>

              <div className="grid md:grid-cols-2 gap-4">
                <Panel title="关键词词云（字号=词频）">
                  <WordCloud data={data?.stats.wordcloud ?? []} height={340} />
                  {/* 只有真的拿到译名才显示这段说明——没有中文时还写「中文为翻译辅助」就是失实 */}
                  {(data?.stats.wordcloud ?? []).some((w) => w.zh) && (
                    <div className="mt-1 text-[11px] leading-5 text-muted">
                      中文为翻译辅助（机翻 + 词典），统计口径仍基于标题/摘要/MeSH 的
                      <b className="font-medium">英文原词</b>；悬停任一词可看英文原文与出现次数。
                    </div>
                  )}
                </Panel>
                <Panel title="研究方向标签">
                  <div className="flex flex-wrap gap-2 pt-2">
                    {(data.stats.topics ?? []).map((t) => (
                      <span
                        key={t.topic}
                        title={`${t.topic} · 出现 ${t.count} 次`}
                        className="inline-flex items-center gap-1 rounded-full bg-brand/10 text-brand text-xs px-3 py-1.5"
                      >
                        {t.zh ?? t.topic} <span className="text-brand/60">×{t.count}</span>
                      </span>
                    ))}
                    {(data.stats.topics ?? []).length === 0 && <span className="text-sm text-muted">暂无足够 MeSH 数据</span>}
                  </div>
                  <div className="mt-2 text-[11px] leading-5 text-muted">
                    {(() => {
                      const hasZh = (data.stats.topics ?? []).some((t) => t.zh);
                      const base =
                        "按 MeSH 词频次自动聚类（纯统计，未调用大模型），已过滤 Humans / Animals / Risk Factors 等无方向区分度的泛化词。";
                      return hasZh
                        ? `词条取自 PubMed 官方 MeSH 主题词（英文受控词表），中文为其译名；悬停可看英文原词。${base}`
                        : `词条取自 PubMed 官方 MeSH 主题词（英文受控词表）。${base}`;
                    })()}
                  </div>
                </Panel>
              </div>

              <section className="rounded-lg border border-line bg-white p-5 shadow-card">
                <div className="flex items-center justify-between mb-3">
                  <h2 className="flex items-center gap-2 text-[15px] font-semibold">
                    <span className="h-3.5 w-1 rounded-full bg-brand" aria-hidden="true" />
                    影响因子 Top {data.stats.top100.length}（近 5 年优先）
                  </h2>
                  <button className="text-xs rounded-md border border-line px-3 py-1.5 text-muted transition-colors hover:text-brand hover:border-brand" onClick={exportCsv}>
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
                      <tr className="text-left text-xs tracking-wide">
                        <th className="px-3 py-2 font-medium">#</th>
                        <th className="px-3 py-2 font-medium">标题</th>
                        <th className="px-3 py-2 font-medium">期刊</th>
                        <th className="px-3 py-2 font-medium">年份</th>
                        <th className="px-3 py-2 font-medium">影响因子</th>
                        <th className="px-3 py-2 font-medium">分区</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.stats.top100.map((r, i) => (
                        <tr key={r.pmid} className="border-t border-line hover:bg-brand/5">
                          <td className="px-3 py-2 text-muted tabular-nums">{i + 1}</td>
                          <td className="px-3 py-2">
                            <a className="hover:text-brand" href={r.url} target="_blank" rel="noreferrer">{r.title || "—"}</a>
                          </td>
                          <td className="px-3 py-2 text-muted">{r.journal || "—"}</td>
                          <td className="px-3 py-2 text-muted tabular-nums">
                            {r.year ?? "—"}
                            {r.in_recent_5y === false && <span className="ml-1 text-[10px] text-accent">补</span>}
                          </td>
                          <td className="px-3 py-2 tabular-nums">{r.impact_factor != null ? r.impact_factor : "—"}</td>
                          <td className="px-3 py-2">
                            {r.quartile ? (
                              // 表格里只用 Q1 这种短标识（用户要求：不要「Q1 一区」）；中文口径挂在悬停提示里
                              <span
                                title={`${quartileLabel(r.quartile)}（Q1=该领域影响因子前 25%，依次递减）`}
                                className={`px-2 py-0.5 rounded text-xs font-medium ${r.quartile === "Q1" ? "bg-green-100 text-green-700" : r.quartile === "Q2" ? "bg-blue-100 text-blue-700" : r.quartile === "Q3" ? "bg-amber-100 text-amber-700" : "bg-red-100 text-red-700"}`}
                              >
                                {r.quartile}
                              </span>
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
                {/* ref 留在标题上：翻页后滚回这里（分页栏只在列表底部一条，顶部不放） */}
                <div ref={artTopRef} className="mb-3">
                  <h2 className="flex items-center gap-2 text-[15px] font-semibold">
                    <span className="h-3.5 w-1 rounded-full bg-brand" aria-hidden="true" />
                    相关文献（本次分析 {data.articles.length} 篇）
                  </h2>
                </div>
                <div className="space-y-3">
                  {artSlice.map((a, i) => (
                    <a key={a.pmid} href={a.url} target="_blank" rel="noreferrer" className="flex gap-3 rounded-md border border-line bg-white p-4 shadow-card transition-all hover:border-brand hover:shadow-lift">
                      {/* 全局序号（跨页连续），便于对上 Top100 与正文引用 */}
                      <span className="w-6 shrink-0 pt-0.5 text-right text-xs tabular-nums text-muted">
                        {(artPageClamped - 1) * artPageSize + i + 1}
                      </span>
                      <span className="min-w-0 flex-1">
                        <div className="text-sm font-medium leading-6">{a.title}</div>
                        <div className="text-xs text-muted mt-1 tabular-nums">
                          {a.journal}
                          {a.year ? ` · ${a.year}` : ""} · PMID:{a.pmid}
                          {a.impact_factor != null ? ` · IF ${a.impact_factor}` : ""}
                        </div>
                      </span>
                    </a>
                  ))}
                </div>
                <div className="mt-3 flex justify-end">
                  <Pager
                    total={artTotal}
                    page={artPageClamped}
                    pageSize={artPageSize}
                    unit="篇"
                    onPage={goArtPage}
                    onPageSize={(n) => {
                      setArtPageSize(n);
                      setArtPage(1);
                    }}
                  />
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
    <div className="rounded-lg border border-line bg-white p-4 shadow-card">
      <div className="text-xs tracking-wide text-muted">{label}</div>
      <div className="text-xl font-semibold mt-1 tabular-nums">{value}</div>
      {sub && <div className="text-xs text-muted mt-1 truncate">{sub}</div>}
    </div>
  );
}

function Feature({ icon, title, desc }: { icon: string; title: string; desc: string }) {
  return (
    <div className="rounded-lg border border-line bg-white p-4 shadow-card transition-all hover:-translate-y-px hover:shadow-lift">
      <div className="flex items-center gap-2">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-brand/10 text-brand">
          <Icon name={icon} />
        </span>
        <span className="text-sm font-medium">{title}</span>
      </div>
      <div className="text-xs text-muted mt-2 leading-6">{desc}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-line bg-white p-5 shadow-card">
      <h2 className="mb-3 flex items-center gap-2 text-[15px] font-semibold">
        <span className="h-3.5 w-1 rounded-full bg-brand" aria-hidden="true" />
        {title}
      </h2>
      {children}
    </section>
  );
}
