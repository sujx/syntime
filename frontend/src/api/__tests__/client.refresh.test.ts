import MockAdapter from "axios-mock-adapter";
import axios from "axios";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  BizError,
  api,
  call,
  configureRefresh,
  resetClientState,
  setTokenProvider,
  type TokenPair,
} from "../client";

let mock: MockAdapter;
let bareMock: MockAdapter;
let store: { pair: TokenPair | null };
let sessionLost: () => void;
let rotated: (a: string, r: string) => void;
let refreshPosts: number;
let authHeaderSeen: string | undefined;

// 不用 as const：readonly 元组不满足 mock 的 MockArrayResponse 可变类型
const OK = (data: unknown): [number, unknown] => [200, { code: 0, message: "ok", data }];

beforeEach(() => {
  mock = new MockAdapter(api);
  bareMock = new MockAdapter(axios);
  store = { pair: { access: "A-1", refresh: "R-1" } };
  sessionLost = vi.fn();
  rotated = vi.fn();
  refreshPosts = 0;
  authHeaderSeen = undefined;
  setTokenProvider(() => store.pair?.access ?? null);
  configureRefresh({
    tokenReader: () => store.pair,
    onTokensRotated: (access, refresh) => rotated(access, refresh),
    onSessionLost: () => sessionLost(),
  });
});
afterEach(() => {
  mock.restore();
  bareMock.restore();
  resetClientState();
});

function wireRefresh(response: [number, unknown]) {
  bareMock.onPost("/api/token/refresh/").reply((cfg) => {
    refreshPosts += 1;
    authHeaderSeen = cfg.headers?.Authorization as string | undefined;
    // 与真实行为对齐：刷新成功后 access/refresh 轮换（信封取 data，失败置 null）
    const body = response[1] as { code: number; data: TokenPair | null };
    store.pair = body.code === 0 ? body.data : null;
    return response;
  });
}

it("并发两个 401 只刷新一次，两个请求都带新 token 重放", async () => {
  wireRefresh([200, { code: 0, message: "ok", data: { access: "A-2", refresh: "R-2" } }]);
  const seen: Array<string | undefined> = [];
  mock.onGet(/\/cost\/summary\//).reply((cfg) => {
    if (cfg.headers?.Authorization === "Bearer A-2") {
      seen.push(cfg.headers.Authorization);
      return OK(1);
    }
    return [401, { code: 40100, message: "登录已过期", data: null }];
  });
  const [a, b] = await Promise.all([
    call<number>({ method: "get", url: "/cost/summary/" }),
    call<number>({ method: "get", url: "/cost/summary/" }),
  ]);
  expect([a, b]).toEqual([1, 1]);
  expect(refreshPosts).toBe(1);
  expect(seen).toEqual(["Bearer A-2", "Bearer A-2"]);
});

it("刷新成功后第三个请求直接复用新 access", async () => {
  wireRefresh([200, { code: 0, message: "ok", data: { access: "A-2", refresh: "R-2" } }]);
  let hits = 0;
  mock.onGet(/\/ping\//).reply((cfg) => {
    hits += 1;
    return cfg.headers?.Authorization === "Bearer A-2"
      ? OK("pong")
      : [401, { code: 40100, message: "登录已过期", data: null }];
  });
  await expect(call({ method: "get", url: "/ping/" })).resolves.toBe("pong");
  await expect(call({ method: "get", url: "/ping/" })).resolves.toBe("pong");
  expect(refreshPosts).toBe(1);
  expect(hits).toBe(3);
  // 后端 ROTATE_REFRESH_TOKENS=True：轮换后的新 refresh 必须交回上层持久化，
  // 否则下次刷新/登出会重发已拉黑的旧 token
  expect(rotated).toHaveBeenCalledWith("A-2", "R-2");
});

it("刷新失败：reject 40100 且 onSessionLost 恰好一次", async () => {
  wireRefresh([401, { code: 40100, message: "登录已过期", data: null }]);
  mock.onGet(/\/ping\//).reply(401, { code: 40100, message: "登录已过期", data: null });
  const err = await call({ method: "get", url: "/ping/" }).catch((e: BizError) => e);
  expect(err).toBeInstanceOf(BizError);
  expect((err as BizError).code).toBe(40100);
  expect(sessionLost).toHaveBeenCalledTimes(1);
  expect(rotated).not.toHaveBeenCalled();
});

it("无 refresh token：不发刷新请求，直接会话丢失", async () => {
  store.pair = null;
  mock.onGet(/\/ping\//).reply(401, { code: 40100, message: "登录已过期", data: null });
  await expect(call({ method: "get", url: "/ping/" })).rejects.toThrow();
  expect(refreshPosts).toBe(0);
  expect(sessionLost).toHaveBeenCalledTimes(1);
});

it("/token/ 自身 401 不触发刷新", async () => {
  wireRefresh([200, { code: 0, message: "ok", data: { access: "X", refresh: "Y" } }]);
  mock.onPost(/\/token\/$/).reply(401, { code: 40100, message: "登录已过期", data: null });
  await expect(call({ method: "post", url: "/token/" })).rejects.toMatchObject({ code: 40100 });
  expect(refreshPosts).toBe(0);
});

it("重放仍 401 不再二次刷新（防死循环）", async () => {
  wireRefresh([200, { code: 0, message: "ok", data: { access: "A-2", refresh: "R-2" } }]);
  let hits = 0;
  mock.onGet(/\/ping\//).reply(() => {
    hits += 1;
    return [401, { code: 40100, message: "登录已过期", data: null }];
  });
  await expect(call({ method: "get", url: "/ping/" })).rejects.toMatchObject({ code: 40100 });
  expect(refreshPosts).toBe(1);
  // GET 总数 = 首次 + 重放 = 2
  expect(hits).toBe(2);
});

it("刷新请求不带 Authorization 头", async () => {
  wireRefresh([200, { code: 0, message: "ok", data: { access: "A-2", refresh: "R-2" } }]);
  mock.onGet(/\/ping\//).reply(401, { code: 40100, message: "登录已过期", data: null });
  await call({ method: "get", url: "/ping/" }).catch(() => undefined);
  expect(authHeaderSeen).toBeUndefined();
});
