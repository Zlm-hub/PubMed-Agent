import { useMemo } from "react";

interface Props {
  data: { word: string; count: number }[];
  height?: number;
  max?: number;
}

// 品牌蓝 4 档，由深到浅：档位与字号严格对应，避免"字号大而颜色浅"的视觉错位
const PALETTE = ["#0b4f9e", "#1573c4", "#2196f3", "#5eb0f0"];

/**
 * 关键词词云（纯 DOM 渲染）。
 *
 * 为什么不用 canvas 版词云插件：canvas 词云依赖实测宽高做贪心排版，在 SPA 中
 * 「容器尺寸未稳 / 图表重绘」时容易整块画不出来，且排布结果不可预期。
 * 这里按词频对字号做 sqrt 压缩（长尾词不会被压成噪点），用 DOM 文本 + flex 居中排布：
 * 渲染确定、可选中可检索、缩放不糊，演示时也不会出现空白面板。
 *
 * 排布取舍：只取词频最高的前 max 个词。词太多会让容器塞满小字、反而看不清层次
 * （超出部分会被 overflow 裁掉），30~40 个词的密度下字号跨度与可读性最平衡。
 */
export default function WordCloud({ data, height = 340, max = 36 }: Props) {
  const items = useMemo(() => {
    const list = (data ?? []).filter((d) => d.word && d.count > 0).slice(0, max);
    if (!list.length) return [];
    const sqrt = (n: number) => Math.sqrt(n);
    const hi = sqrt(list[0].count);
    const lo = sqrt(list[list.length - 1].count);
    const span = hi - lo || 1;
    return list.map((d) => {
      const t = (sqrt(d.count) - lo) / span; // 0(最小) → 1(最大)
      const size = 15 + t * 26; // 15px ~ 41px
      const tier = Math.min(PALETTE.length - 1, Math.floor((1 - t) * PALETTE.length));
      return {
        word: d.word,
        count: d.count,
        size,
        color: PALETTE[tier],
        weight: t > 0.6 ? 700 : t > 0.3 ? 600 : 500,
      };
    });
  }, [data, max]);

  if (!items.length) {
    return (
      <div className="flex items-center justify-center text-sm text-muted" style={{ height }}>
        暂无足够关键词
      </div>
    );
  }

  return (
    <div
      className="flex flex-wrap items-center justify-center content-center overflow-hidden px-3"
      style={{ height, gap: "6px 14px" }}
      title="字号与颜色深浅代表关键词在标题/摘要/MeSH 中的出现频次"
    >
      {items.map((it) => (
        <span
          key={it.word}
          className="transition-transform duration-150 hover:scale-110 cursor-default select-none"
          style={{
            fontSize: it.size,
            lineHeight: 1.05,
            color: it.color,
            fontWeight: it.weight,
          }}
          title={`${it.word}：出现 ${it.count} 次`}
        >
          {it.word}
        </span>
      ))}
    </div>
  );
}
