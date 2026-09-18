import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, PieChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsOption } from "echarts";
import type { EChartsType } from "echarts/core";

// 按需注册：只引入本项目实际用到的图表与组件（柱状图 / 环形图 + 坐标系 / 提示框 / 图例）。
// 相比 `import * as echarts from "echarts"` 全量引入，产物体积约减半。
// 新增图表类型时记得在此补充注册，否则该系列会静默不渲染。
echarts.use([BarChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer]);

interface Props {
  option: EChartsOption;
  height?: number;
  className?: string;
}

export default function EChart({ option, height = 300, className }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<EChartsType | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    // 容器尺寸变化（布局完成、字体加载、窗口缩放）时跟随重算，避免图表留白或错位
    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(ref.current);
    return () => {
      window.removeEventListener("resize", onResize);
      ro.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.setOption(option, true);
    // 首帧容器尺寸可能尚未稳定，下一帧补一次 resize，让图表按最终尺寸重绘
    const raf = requestAnimationFrame(() => {
      if (chartRef.current) chartRef.current.resize();
    });
    return () => cancelAnimationFrame(raf);
  }, [option]);

  return <div ref={ref} className={className} style={{ width: "100%", height }} />;
}
