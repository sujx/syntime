import "@testing-library/jest-dom/vitest";

// Node 25+ 把 globalThis.localStorage 定义成需要 --localstorage-file 的 accessor，
// getter 恒返回 undefined，并连带遮蔽 jsdom 的实现：vitest 的 jsdom 环境里
// window === globalThis，故 window.localStorage 同为 undefined，而 globalThis.Storage
// 又是 Illegal constructor，无法自行实例化。令牌读写用例全依赖它。
// 这里按 WHATWG Storage 语义补一个内存实现（键与值一律转字符串、缺失返回 null、
// key() 按插入顺序、removeItem 对缺失键静默）。
class MemoryStorage {
  private readonly entries = new Map<string, string>();

  get length(): number {
    return this.entries.size;
  }

  clear(): void {
    this.entries.clear();
  }

  getItem(key: string): string | null {
    return this.entries.get(String(key)) ?? null;
  }

  key(index: number): string | null {
    return [...this.entries.keys()][index] ?? null;
  }

  removeItem(key: string): void {
    this.entries.delete(String(key));
  }

  setItem(key: string, value: string): void {
    this.entries.set(String(key), String(value));
  }
}

Object.defineProperty(globalThis, "localStorage", {
  value: new MemoryStorage(),
  configurable: true,
  writable: true,
});

// jsdom 未实现 matchMedia，antd Table/Drawer 响应式观察器依赖它
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

// jsdom 的 getComputedStyle 极慢且 rc-table scroll.x 触发的伪元素测量未实现，
// 用轻量桩替换：role 查询的隐藏元素计算与滚动条测量均走此函数
const fakeStyle = {
  getPropertyValue: () => "",
  display: "block",
  visibility: "visible",
  width: "0px",
  height: "0px",
  overflow: "visible",
};
window.getComputedStyle = (() => fakeStyle) as unknown as typeof window.getComputedStyle;
