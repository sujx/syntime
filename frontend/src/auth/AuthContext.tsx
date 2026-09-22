// Context + Provider + useAuth 同文件是 React 惯例；useAuth 导出使 react-refresh 无法按纯组件文件热更新，仅影响开发态 HMR
/* eslint-disable react-refresh/only-export-components */
import { Alert } from "antd";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { BizError, configureRefresh, post, setTokenProvider } from "@/api/client";
import { API } from "@/api/endpoints";
import { isRole, type Role } from "./roles";
import * as tokenStore from "./tokenStore";

type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthValue {
  status: AuthStatus;
  username: string | null;
  role: Role | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

interface LoginData {
  access: string;
  refresh: string;
  role: unknown;
  username: string;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [username, setUsername] = useState<string | null>(null);
  const [role, setRole] = useState<Role | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTokenProvider(tokenStore.getAccess);
    configureRefresh({
      // 会话恢复后 access 可能尚为 null：只要有 refresh 就返回对（access 占位空串），
      // 刷新成功回调 onAccessRotated 会以真实 access 覆盖
      tokenReader: () => {
        const refresh = tokenStore.getRefresh();
        return refresh ? { access: tokenStore.getAccess() ?? "", refresh } : null;
      },
      onAccessRotated: (access) => tokenStore.setAccess(access),
      onSessionLost: () => {
        // 可被并发请求链重复触发：清空 + 复位天然幂等，无需加锁
        tokenStore.clear();
        setTokenProvider(null);
        configureRefresh(null);
        setStatus("anonymous");
        setUsername(null);
        setRole(null);
      },
    });
    const session = tokenStore.readSession();
    if (session && tokenStore.getRefresh()) {
      setUsername(session.username);
      setRole(session.role);
      setStatus("authenticated"); // access 为空，首个 401 触发刷新换发
    } else {
      tokenStore.clear();
      setStatus("anonymous");
    }
    return () => {
      setTokenProvider(null);
      configureRefresh(null);
    };
  }, []);

  const login = useCallback(async (name: string, password: string) => {
    setError(null);
    try {
      const data = await post<LoginData>(API.token, { username: name, password });
      if (!isRole(data.role)) {
        const msg = "该账号未分配平台角色";
        setError(msg);
        throw new BizError(msg, 40001, 400);
      }
      tokenStore.setAccess(data.access);
      tokenStore.setRefresh(data.refresh);
      tokenStore.writeSession({ username: data.username, role: data.role });
      setUsername(data.username);
      setRole(data.role);
      setStatus("authenticated");
    } catch (err) {
      if (err instanceof BizError) setError(err.message);
      throw err;
    }
  }, []);

  const logout = useCallback(async () => {
    const refresh = tokenStore.getRefresh();
    try {
      if (refresh) await post<null>(API.logout, { refresh });
    } catch {
      /* 服务端黑名单失败不阻塞本地登出 */
    } finally {
      tokenStore.clear();
      setUsername(null);
      setRole(null);
      setStatus("anonymous");
    }
  }, []);

  const value = useMemo(
    () => ({ status, username, role, login, logout }),
    [status, username, role, login, logout],
  );

  return (
    <AuthContext.Provider value={value}>
      {error && (
        <Alert type="error" message={error} banner closable onClose={() => setError(null)} />
      )}
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 <AuthProvider> 内使用");
  return ctx;
}
