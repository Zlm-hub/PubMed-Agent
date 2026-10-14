/**
 * 通用分页条（自包含）：每页条数选择 + 页码导航。
 *
 * 目前用于报告页「相关文献」列表；Top100 表格将来若要分页可直接复用。
 * 页码多时用省略号收窄窗口（始终保留首页/末页与当前页前后各一页），避免 40 页时按钮铺满一行。
 */

const DEFAULT_SIZES = [5, 10, 15, 20];

/** 页码窗口：页数少则全列，页数多则 1 … page-1 page page+1 … N */
function pageWindow(page: number, pages: number): (number | "gap")[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const keep = new Set<number>([1, pages, page - 1, page, page + 1]);
  const sorted = [...keep].filter((p) => p >= 1 && p <= pages).sort((a, b) => a - b);
  const out: (number | "gap")[] = [];
  sorted.forEach((p, i) => {
    if (i > 0 && p - sorted[i - 1] > 1) out.push("gap");
    out.push(p);
  });
  return out;
}

const BTN =
  "rounded border border-line px-2 py-0.5 tabular-nums transition-colors hover:border-brand hover:text-brand disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:border-line disabled:hover:text-muted";
const ACTIVE = "rounded border border-brand bg-brand/10 px-2 py-0.5 font-medium tabular-nums text-brand";

export default function Pager({
  total,
  page,
  pageSize,
  onPage,
  onPageSize,
  sizes = DEFAULT_SIZES,
  unit = "条",
}: {
  total: number;
  page: number;
  pageSize: number;
  onPage: (p: number) => void;
  onPageSize: (n: number) => void;
  sizes?: number[];
  unit?: string;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-xs text-muted">
      <span className="tabular-nums">
        共 {total} {unit} · 第 {page} / {pages} 页
      </span>

      <span className="flex items-center gap-1">
        <span>每页</span>
        {sizes.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onPageSize(n)}
            aria-pressed={n === pageSize}
            className={n === pageSize ? ACTIVE : BTN}
          >
            {n}
          </button>
        ))}
        <span>{unit}</span>
      </span>

      <span className="flex items-center gap-1">
        <button type="button" className={BTN} disabled={page <= 1} onClick={() => onPage(page - 1)}>
          上一页
        </button>
        {pageWindow(page, pages).map((p, i) =>
          p === "gap" ? (
            <span key={`gap-${i}`} className="px-1 text-muted/60">
              …
            </span>
          ) : (
            <button
              key={p}
              type="button"
              onClick={() => onPage(p)}
              aria-current={p === page ? "page" : undefined}
              className={p === page ? ACTIVE : BTN}
            >
              {p}
            </button>
          ),
        )}
        <button type="button" className={BTN} disabled={page >= pages} onClick={() => onPage(page + 1)}>
          下一页
        </button>
      </span>
    </div>
  );
}
