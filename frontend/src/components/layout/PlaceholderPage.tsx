import { Card } from "antd";
import type { ReactNode } from "react";
import { zh } from "@/i18n/zh";
import styles from "./PlaceholderPage.module.css";

export function PlaceholderPage({
  titleKey,
  phase2 = true,
  children,
}: {
  titleKey: string;
  phase2?: boolean;
  children?: ReactNode;
}) {
  return (
    <Card variant="borderless">
      <div className={styles.head}>
        <h1 className="page-title">{zh[titleKey]}</h1>
        {phase2 && <span className={styles.pill}>{zh["placeholder.phase2"]}</span>}
      </div>
      {children}
    </Card>
  );
}

export function Phase2Note() {
  return <p className={styles.note}>{zh["placeholder.phase2Note"]}</p>;
}

export function ImportDropzone() {
  return (
    <div className={styles.dropzone}>
      <div
        style={{
          fontWeight: 600,
          color: "var(--gray-700)",
          marginBottom: "var(--space-2)",
        }}
      >
        {zh["import.sectionTitle"]}
      </div>
      <div>{zh["import.dropHint"]}</div>
      <div style={{ fontSize: 12, marginTop: "var(--space-2)" }}>{zh["import.templateHint"]}</div>
    </div>
  );
}
