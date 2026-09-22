import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import type { EChartsOption } from "echarts";
import { zh } from "@/i18n/zh";
import styles from "./ChartCard.module.css";

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  CanvasRenderer,
]);

export function ChartCard({
  title,
  extra,
  option,
  height = 280,
}: {
  title: string;
  extra?: string;
  option?: EChartsOption;
  height?: number;
}) {
  const el = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!option || !el.current) return;
    const chart = echarts.init(el.current);
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [option]);
  return (
    <section className={styles.card}>
      <div className={styles.head}>
        <span className={styles.title}>{title}</span>
        {extra && <span className={styles.extra}>{extra}</span>}
      </div>
      {/* §5.6-9：图表宿主节点常驻不销毁，空态以绝对定位覆盖层呈现 */}
      <div className={styles.body}>
        <div ref={el} data-testid={`chart:${title}`} style={{ height }} />
        {option ? null : <div className={styles.pending}>{zh["chart.pending"] ?? ""}</div>}
      </div>
    </section>
  );
}
