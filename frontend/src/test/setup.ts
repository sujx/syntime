import "@testing-library/jest-dom/vitest";

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
