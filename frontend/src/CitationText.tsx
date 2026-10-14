/**
 * 综述正文的 PMID 引用渲染：把 [PMID: 12345678] 解析成可点击链接。
 *
 * 后端正文里的引用写法实测不统一，至少三种：
 *   [PMID:37477236]（冒号后无空格）
 *   [PMID: 29079157]（有空格）
 *   [PMID: 32059825; PMID: 31433675]（一条括号里多个）
 * 因此匹配策略是「方括号里出现 PMID 就整段当引用」，段内按 `PMID + 数字` 逐条成链，
 * 不写死分隔符，避免模型的空格/分号习惯变化就失效。
 * 段内写坏的部分（如 `[PMID: 29079157; PMID: 25]` 里的 `PMID: 25`，位数不足）**原样保留**，
 * 不做半截链接、也不静默吞掉。
 *
 * 悬停提示取自**同一次响应**的 articles（真实标题/期刊/年份）；查不到就退化为纯 PMID，
 * 绝不编造文献信息——与本项目「可溯源」的口径一致。
 */
import type { ReactNode } from "react";
import type { Article } from "./api";

/** 括号内含 PMID 即视为引用片段 */
const CITE_RE = /\[[^\]]*PMID[^\]]*\]/gi;
/** 单条合法引用：PMID + 可选冒号 + 4~9 位数字（取 4 位以上以避开「2024」这类年份） */
const PMID_ITEM_RE = /PMID\s*[:：]?\s*(\d{4,9})/gi;

function tipFor(id: string, articles: Article[]): string {
  const art = articles.find((a) => a.pmid === id);
  if (!art) return `PubMed PMID ${id}`;
  const parts = [art.title, art.journal, art.year != null ? String(art.year) : ""];
  return parts.filter(Boolean).join(" · ");
}

/** 括号内容 → 节点序列：合法 PMID 成链，分隔符与写坏的残渣原样保留（不静默吞掉信息） */
function renderBracket(raw: string, articles: Article[], keyBase: string): ReactNode[] {
  const inner = raw.slice(1, -1);
  const parts: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of inner.matchAll(PMID_ITEM_RE)) {
    const start = m.index ?? 0;
    if (start > last) parts.push(inner.slice(last, start));
    const id = m[1];
    parts.push(
      <a
        key={`${keyBase}-${i}`}
        href={`https://pubmed.ncbi.nlm.nih.gov/${id}/`}
        target="_blank"
        rel="noreferrer"
        title={tipFor(id, articles)}
        className="rounded px-0.5 font-medium text-brand transition-colors hover:bg-brand/10"
      >
        PMID&nbsp;{id}
      </a>,
    );
    i += 1;
    last = start + m[0].length;
  }
  if (last < inner.length) parts.push(inner.slice(last));
  return ["[", ...parts, "]"];
}

export default function CitationText({ text, articles }: { text: string; articles: Article[] }) {
  const nodes: ReactNode[] = [];
  let last = 0;

  for (const m of text.matchAll(CITE_RE)) {
    const start = m.index ?? 0;
    if (start > last) nodes.push(text.slice(last, start));
    nodes.push(
      <span key={`cite-${start}`} className="whitespace-nowrap">
        {renderBracket(m[0], articles, `cite-${start}`)}
      </span>,
    );
    last = start + m[0].length;
  }

  if (last < text.length) nodes.push(text.slice(last));
  return <>{nodes}</>;
}
