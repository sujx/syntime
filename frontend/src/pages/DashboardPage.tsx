import { Button, Empty, Skeleton } from "antd";
import type { ReactNode } from "react";
import { ChartCard } from "@/components/chart/ChartCard";
import { useDashboard } from "@/features/dashboard/hooks";
import { buildResourceTrendOption } from "@/features/charts/trendOption";
import { useAuth } from "@/hooks/useAuth";
import { zh } from "@/i18n/zh";
import styles from "./dashboard/dashboard.module.css";

function fmtTime(iso: string | null): string {
  return iso ? iso.replace("T", " ").slice(0, 16) : (zh["dash.never"] ?? "");
}

export default function DashboardPage() {
  const { username } = useAuth();
  const { data, isPending, isError, refetch } = useDashboard();

  return (
    <div data-testid="page-dashboard">
      <h1 className="page-title" style={{ marginBottom: "var(--space-5)" }}>
        {zh["nav.dashboard"]}
        {username ? (
          <span
            style={{
              fontSize: 13,
              fontWeight: 400,
              color: "var(--gray-500)",
              marginLeft: "var(--space-3)",
            }}
          >
            {username}
          </span>
        ) : null}
      </h1>
      {isPending ? <Skeleton active paragraph={{ rows: 8 }} /> : null}
      {isError && !data ? (
        <Empty description={zh["common.loadFail"]}>
          <Button autoInsertSpace={false} onClick={() => void refetch()}>
            {zh["common.retry"]}
          </Button>
        </Empty>
      ) : null}
      {data ? (
        <>
          <div className={styles.kpiGrid}>
            <Kpi
              label={zh["dash.kpiCloud"] ?? ""}
              value={data.cards.cloudAccountTotal}
              sub={`${zh["dash.enabled"]} ${data.cards.enabled} · ${zh["dash.disabled"]} ${data.cards.disabled}`}
            />
            <Kpi
              label={zh["dash.kpiAsset"] ?? ""}
              value={data.cards.assetTotal}
              sub={`${zh["dash.running"]} ${data.cards.running} · ${zh["dash.stopped"]} ${data.cards.stopped}`}
            />
            <Kpi
              label={zh["dash.kpiMonth"] ?? ""}
              value={data.cards.monthAmount}
              sub={
                <>
                  <span
                    className={`${styles.pill} ${data.cards.monthRate === "--" ? styles.neutral : Number(data.cards.monthRate) >= 0 ? styles.up : styles.down}`}
                  >
                    {data.cards.monthRate === "--"
                      ? "--"
                      : `${Number(data.cards.monthRate) >= 0 ? "↑" : "↓"} ${data.cards.monthRate}%`}
                  </span>
                  {data.cards.isEstimate ? (
                    <span className={`${styles.pill} ${styles.neutral}`}>
                      {zh["dash.estimateTag"]}
                    </span>
                  ) : null}
                </>
              }
            />
            <Kpi
              label={zh["dash.kpiUnallocated"] ?? ""}
              value={data.cards.unallocatedAmount}
              sub={`${zh["dash.ratio"]} ${data.cards.unallocatedRatio}%`}
            />
            <Kpi
              label={zh["dash.kpiEvent"] ?? ""}
              value={data.cards.eventPending}
              sub={`${zh["dash.high"]} ${data.cards.eventHigh} · ${zh["dash.warning"]} ${data.cards.eventWarning}`}
            />
          </div>
          <div className={styles.cols}>
            <ChartCard
              title={zh["dash.trendTitle"] ?? ""}
              extra={zh["dash.trendExtra"]}
              emptyText={zh["gov.empty"]}
              option={
                data.trend.current.length > 0 ? buildResourceTrendOption(data.trend) : undefined
              }
              height={300}
            />
            <section className={styles.kpi}>
              <div
                className={styles.label}
                style={{ fontWeight: 600, fontSize: 15, color: "var(--gray-900)" }}
              >
                {zh["dash.syncTitle"]}
              </div>
              <div className={styles.syncRow}>
                <span>{zh["dash.lastAggregate"]}</span>
                <span className={styles.time}>{fmtTime(data.syncStatus.lastAggregateTime)}</span>
              </div>
              {data.syncStatus.accounts.map((a) => (
                <div className={styles.syncRow} key={a.accountName}>
                  <span>
                    <span
                      className={styles.dot}
                      style={{
                        background:
                          a.status === "failed"
                            ? "#DC2626"
                            : a.status === "running"
                              ? "#D97706"
                              : "#10B981",
                      }}
                    />
                    {a.accountName}
                    <span
                      style={{ color: "var(--gray-400, #94a3b8)", marginLeft: 6, fontSize: 12 }}
                    >
                      {a.vendor}
                    </span>
                  </span>
                  <span className={styles.time}>{fmtTime(a.lastSyncTime)}</span>
                </div>
              ))}
            </section>
          </div>
        </>
      ) : null}
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string | number; sub: ReactNode }) {
  return (
    <div className={styles.kpi}>
      <div className={styles.bar} />
      <div className={styles.label}>{label}</div>
      <div className={styles.value}>{value}</div>
      <div className={styles.sub}>{sub}</div>
    </div>
  );
}
