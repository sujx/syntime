import { useLocation } from "react-router-dom";
import { zh } from "@/i18n/zh";
import { findItem } from "@/nav/menu";
import styles from "./layout.module.css";

export function Topbar() {
  const { pathname } = useLocation();
  const item = findItem(pathname);
  return (
    <header className={styles.topbar}>
      <span className={styles.crumb}>{zh["brand.name"]}</span>
      <span className={styles.crumb}>/</span>
      <span className={styles.crumbCurrent}>{item ? zh[item.labelKey] : zh["nav.dashboard"]}</span>
      <span className={styles.syncChip}>{zh["shell.syncChip"]}</span>
    </header>
  );
}
