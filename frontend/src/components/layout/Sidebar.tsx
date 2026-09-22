import {
  AlertOutlined,
  BellOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  FundOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  WalletOutlined,
} from "@ant-design/icons";
import { Tooltip } from "antd";
import { NavLink } from "react-router-dom";
import { Seal, Wordmark } from "@/brand/brand";
import { useAuth } from "@/hooks/useAuth";
import { useUnreadBadge } from "@/hooks/useUnreadBadge";
import { zh } from "@/i18n/zh";
import { visibleNav, type NavItem } from "@/nav/menu";
import styles from "./layout.module.css";

const ICONS: Record<string, React.ReactNode> = {
  dashboard: <DashboardOutlined />,
  projectSettlement: <FundOutlined />,
  budget: <WalletOutlined />,
  governance: <SafetyCertificateOutlined />,
  asset: <CloudServerOutlined />,
  cloudAccount: <CloudServerOutlined />,
  event: <BellOutlined />,
  alertConfig: <AlertOutlined />,
};

function badgeText(n: number): string {
  return n > 99 ? "99+" : String(n);
}

export function Sidebar() {
  const { role, username, logout } = useAuth();
  const unread = useUnreadBadge(role !== null);
  return (
    <aside className={styles.sidebar}>
      <div className={styles.inner}>
        <div className={styles.brand}>
          <Seal size={32} />
          <span className={styles.brandText}>
            <Wordmark onDark size={17} />
          </span>
        </div>
        <nav>
          {visibleNav(role).map((group) => (
            <div key={group.titleKey} className={styles.group}>
              <div className={styles.groupTitle}>{zh[group.titleKey]}</div>
              {group.items.map((item: NavItem) => {
                const link = (
                  <NavLink
                    key={item.key}
                    to={item.path}
                    className={({ isActive }) =>
                      `${styles.item} ${isActive ? styles.itemActive : ""}`
                    }
                  >
                    {ICONS[item.key]}
                    <span className={styles.itemLabel}>{zh[item.labelKey]}</span>
                    {item.badge === "eventUnread" && unread > 0 && (
                      <span className={styles.badge}>{badgeText(unread)}</span>
                    )}
                  </NavLink>
                );
                return (
                  <Tooltip key={item.key} title={zh[item.labelKey]} placement="right">
                    <span style={{ display: "block" }}>{link}</span>
                  </Tooltip>
                );
              })}
            </div>
          ))}
        </nav>
        <div className={styles.spacer} />
        <div className={styles.user}>
          <span className={styles.avatar}>{username?.[0]?.toUpperCase() ?? "?"}</span>
          <span className={styles.userName}>{username}</span>
          <Tooltip title={zh["shell.logout"]}>
            <button
              type="button"
              className={styles.logoutBtn}
              aria-label={zh["shell.logout"]}
              onClick={() => void logout()}
            >
              <LogoutOutlined />
            </button>
          </Tooltip>
        </div>
      </div>
    </aside>
  );
}
