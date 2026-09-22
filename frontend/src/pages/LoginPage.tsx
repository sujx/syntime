import { CheckCircleFilled, LockOutlined, MobileOutlined, UserOutlined } from "@ant-design/icons";
import { App as AntdApp, Button, Checkbox, Input } from "antd";
import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { BizError } from "@/api/client";
import { Seal, Wordmark } from "@/brand/brand";
import { useAuth } from "@/hooks/useAuth";
import { zh } from "@/i18n/zh";
import { DEFAULT_PATH, findItem } from "@/nav/menu";
import styles from "./login/login.module.css";

export default function LoginPage() {
  const { login } = useAuth();
  const { message } = AntdApp.useApp();
  const navigate = useNavigate();
  const location = useLocation();
  const [tab, setTab] = useState<"pwd" | "sms">("pwd");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (submitting) return;
    if (!username || !password) return;
    setSubmitting(true);
    try {
      await login(username, password);
      const from = (location.state as { from?: string } | null)?.from;
      const target = from && findItem(from) !== undefined ? from : DEFAULT_PATH;
      navigate(target, { replace: true });
    } catch (err) {
      if (!(err instanceof BizError)) message.error(zh["login.fail"]);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className={styles.screen}>
      <div className={styles.brand}>
        <Seal size={30} />
        <Wordmark onDark size={16} />
      </div>
      <div className={styles.hero}>
        <h1>{zh["brand.slogan"]}</h1>
        <div className={styles.feats}>
          {["login.heroFeat1", "login.heroFeat2", "login.heroFeat3"].map((k) => (
            <div key={k} className={styles.feat}>
              <span className={styles.ck}>
                <CheckCircleFilled />
              </span>
              {zh[k]}
            </div>
          ))}
        </div>
      </div>
      <div className={styles.card}>
        <div className={styles.cardHead}>
          <Seal size={52} />
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, color: "var(--gray-900)" }}>
              {zh["login.title"]}
            </div>
            <div style={{ fontSize: 12, color: "var(--gray-500)", marginTop: 2 }}>
              {zh["brand.name"]}
            </div>
          </div>
        </div>
        <div className={styles.tabs}>
          <button
            type="button"
            aria-pressed={tab === "pwd"}
            className={tab === "pwd" ? `${styles.tab} ${styles.tabOn}` : styles.tab}
            onClick={() => setTab("pwd")}
          >
            {zh["login.tabPassword"]}
          </button>
          <button
            type="button"
            aria-pressed={tab === "sms"}
            className={tab === "sms" ? `${styles.tab} ${styles.tabOn}` : styles.tab}
            onClick={() => {
              setTab("sms");
              message.info(zh["login.smsTodo"]);
            }}
          >
            {zh["login.tabSms"]}
          </button>
        </div>
        {tab === "pwd" ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <div className={styles.inputWrap}>
              <UserOutlined className={styles.inputIcon} />
              <Input
                className={styles.input}
                size="large"
                aria-label={zh["login.username"]}
                placeholder={zh["login.username"]}
                prefix={<span />}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
              />
            </div>
            <div className={styles.inputWrap}>
              <LockOutlined className={styles.inputIcon} />
              <Input.Password
                className={styles.input}
                size="large"
                aria-label={zh["login.password"]}
                placeholder={zh["login.password"]}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </div>
            <div className={styles.row}>
              <Checkbox>{zh["login.remember"]}</Checkbox>
            </div>
            <Button
              className={styles.submit}
              type="primary"
              htmlType="submit"
              loading={submitting}
              block
            >
              {zh["login.submit"]}
            </Button>
          </form>
        ) : (
          <Input
            size="large"
            prefix={<MobileOutlined />}
            placeholder={zh["login.smsTodo"]}
            disabled
          />
        )}
        <div className={styles.agree}>{zh["login.agreement"]}</div>
        <div className={styles.divider}>或</div>
        <Button className={styles.sso} block disabled aria-hidden>
          {zh["login.sso"]}
        </Button>
      </div>
      <div className={styles.copy}>{zh["login.copyright"]}</div>
    </div>
  );
}
