import * as echarts from "echarts";
import { useEffect, useRef } from "react";
import type { EChartsOption } from "echarts";
import { zh } from "@/i18n/zh";
import styles from "./ChartCard.module.css";

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
      {option ? (
        <div ref={el} style={{ height }} />
      ) : (
        <div className={styles.pending} style={{ height }}>
          {zh["chart.pending"]}
        </div>
      )}
    </section>
  );
}
