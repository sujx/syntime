import styles from "./brand.module.css";

export function Seal({ size = 36 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      role="img"
      aria-label="SynTime"
      style={{ display: "block", flexShrink: 0 }}
    >
      <rect width="64" height="64" rx="14" fill="var(--seal-red)" />
      <text
        x="32"
        y="42"
        fontSize="34"
        textAnchor="middle"
        fill="#fff"
        fontFamily="'STKaiti','KaiTi','楷体',serif"
      >
        偕
      </text>
    </svg>
  );
}

export function Wordmark({ onDark = false, size = 18 }: { onDark?: boolean; size?: number }) {
  return (
    <span
      className={`${styles.wordmark} ${onDark ? styles.onDark : styles.onLight}`}
      style={{ fontSize: size }}
    >
      <span className={styles.syn}>Syn</span>
      <span className={styles.time}>Time</span>
    </span>
  );
}
