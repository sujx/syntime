import { Empty } from "antd";
import { useAuth } from "@/hooks/useAuth";
import { zh } from "@/i18n/zh";

export default function DashboardPage() {
  const { username } = useAuth();
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
      <Empty description={zh["placeholder.dataWiring"]} />
    </div>
  );
}
