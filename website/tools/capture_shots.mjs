// 宣传站素材截图：headless Chromium + CDP 驱动高保真原型，1440px 宽视口逐页整页截图。
//
//   node website/tools/capture_shots.mjs [--prototype <原型.html>] [--out <目录>] [--only login,dashboard,...]
//
// 默认输出 website/source/images/_shots/（PNG 母图，2x），已生成好的 WebP/PNG 交付物由
// tools/build_images.sh 转换。切页走原型自身的 .sb-item 点击处理器，不伪造 DOM——
// 截图所见即原型在当前环境下的真实渲染（含原型自身的排版缺陷，勿后期修图掩盖）。
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ARGS = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = ARGS.indexOf(`--${name}`);
  return i === -1 ? fallback : ARGS[i + 1];
};

const PROTOTYPE = resolve(opt("prototype", join(HERE, "../../../高保真原型_多云成本管理平台.html")));
const OUT = resolve(opt("out", join(HERE, "../source/images/_shots")));
const WIDTH = 1440;
const HEIGHT = 900;
const DSF = 2;
// 不用固定 sleep 赌 ECharts 动画：show() 内部是 setTimeout(renderCharts,50)，
// 再叠加 .page fadeUp(.35s)，固定等待会拍到半截曲线（实测 1800ms 仍不够）。
// 改为等所有可见图表实例派发 'finished'，兜底 6s 超时防挂死。
const WAIT_CHARTS = `(async()=>{
  const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
  await sleep(120); /* show() 的 setTimeout(renderCharts,50) 已建实例，动画刚起步 */
  const els=[...document.querySelectorAll('.chart-box,.spark')].filter(e=>e.offsetParent!==null);
  let timedOut=0;
  await Promise.all(els.map(el=>new Promise(res=>{
    const c=window.echarts&&echarts.getInstanceByDom(el);
    if(!c)return res();
    let done=false;
    const t=setTimeout(()=>{if(!done){done=true;timedOut++;res();}},2500);
    c.on('finished',()=>{if(!done){done=true;clearTimeout(t);res();}});
  })));
  await sleep(250);
  return JSON.stringify({charts:els.length,timedOut});})()`;

// page = 原型 data-page 值；file 必须与 copy.yml gallery 的 image 名对齐
const SHOTS = [
  { page: "login", file: "login.png" },
  { page: "billing", file: "settlement.png" },
  { page: "dashboard", file: "dashboard.png" },
  { page: "events", file: "events.png" },
  { page: "govern", file: "governance.png" },
];
const only = opt("only", null)?.split(",").filter(Boolean);
const PORT = Number(opt("port", 9333));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const proc = spawn(
  "/usr/bin/chromium",
  ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${join(HERE, ".chrome-profile")}`,
   "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--hide-scrollbars",
   "--force-color-profile=srgb", "--font-render-hinting=none", "--lang=zh-CN",
   `--window-size=${WIDTH},${HEIGHT}`, "about:blank"],
  { stdio: ["ignore", "ignore", "pipe"] },
);
let chromiumLog = "";
proc.stderr.on("data", (d) => (chromiumLog += d.toString()));

async function connect() {
  for (let i = 0; i < 60; i++) {
    try {
      const v = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
      return new Promise((res, rej) => {
        const ws = new WebSocket(v.webSocketDebuggerUrl);
        ws.onopen = () => res(ws);
        ws.onerror = (e) => rej(new Error(`ws 失败: ${e.message ?? e.type}`));
      });
    } catch {
      await sleep(500);
    }
  }
  throw new Error("chromium 调试端口未就绪");
}

let ws;
try {
  mkdirSync(OUT, { recursive: true });
  ws = await connect();
  let nextId = 1;
  const pending = new Map();
  const events = new Map();
  ws.onmessage = (raw) => {
    const msg = JSON.parse(raw.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve: ok, reject: no } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? no(new Error(JSON.stringify(msg.error))) : ok(msg.result);
    } else if (msg.method) {
      events.set(msg.method, [...(events.get(msg.method) || []), msg]);
    }
  };
  const send = (method, params = {}, sessionId) =>
    new Promise((ok, no) => {
      const id = nextId++;
      pending.set(id, { resolve: ok, reject: no });
      ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
  const waitEvent = async (method, sessionId, timeoutMs = 30000) => {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const hit = (events.get(method) || []).find((m) => m.sessionId === sessionId);
      if (hit) return hit;
      if (Date.now() > deadline) throw new Error(`等待 ${method} 超时`);
      await sleep(50);
    }
  };

  const { targetId } = await send("Target.createTarget", { url: "about:blank" });
  const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
  await send("Page.enable", {}, sessionId);
  await send("Runtime.enable", {}, sessionId);
  await send("Emulation.setDeviceMetricsOverride",
    { width: WIDTH, height: HEIGHT, deviceScaleFactor: DSF, mobile: false }, sessionId);

  const evaluate = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId);
    if (r.exceptionDetails) throw new Error("页内脚本异常: " + JSON.stringify(r.exceptionDetails));
    return r.result?.value;
  };
  const reload = async () => {
    events.set("Page.loadEventFired", []);
    await send("Page.navigate", { url: pathToFileURL(PROTOTYPE).href }, sessionId);
    await waitEvent("Page.loadEventFired", sessionId);
    await sleep(800); // vendor/echarts.min.js + 字体就位
    // 冻结「无限循环」动画：仪表盘 `.sync-dot.run i` 的 pulse（opacity 1↔.4 / 1.5s）
    // 会让同一页两次截图差 ~194 px（拍到的相位不同）。只停这一类，不动入场动画
    // （cardIn 带 fill:both，全局 animation:none 会让登录卡回退到未居中的基线样式）。
    await evaluate(
      "(()=>{if(!document.getElementById('shot-freeze')){const s=document.createElement('style');" +
      "s.id='shot-freeze';s.textContent='.sync-dot.run i{animation:none!important}';" +
      "document.head.appendChild(s);}return 1})()");
  };

  await reload();
  console.log("原型 " + PROTOTYPE);
  console.log("环境 " + (await evaluate(
    "JSON.stringify({vw:innerWidth,vh:innerHeight,dpr:devicePixelRatio,echarts:typeof echarts})")));

  for (const shot of SHOTS.filter((s) => !only || only.includes(s.page))) {
    await reload();
    if (shot.page !== "login") {
      await evaluate("doLogin()");
      const clicked = await evaluate(
        `(()=>{const b=document.querySelector('.sb-item[data-page="${shot.page}"]');` +
        `if(!b)return 'NO-BUTTON';b.click();return b.dataset.page})()`);
      if (clicked !== shot.page) throw new Error(`${shot.page} 导航失败：${clicked}`);
    }
    await sleep(600); // CSS 入场（.page fadeUp .35s / 登录卡 cardIn）
    await evaluate(WAIT_CHARTS).then((r) => console.log(`  图表就位 ${r}`));
    const { data } = await send("Page.captureScreenshot",
      { format: "png", captureBeyondViewport: true, fromSurface: true }, sessionId);
    writeFileSync(join(OUT, shot.file), Buffer.from(data, "base64"));
    const box = await evaluate(
      "JSON.stringify([document.documentElement.scrollWidth,document.documentElement.scrollHeight])");
    console.log(`OK ${shot.page} -> ${shot.file} 文档尺寸 ${box}`);
  }
} finally {
  ws?.close();
  proc.kill("SIGTERM");
  await sleep(300);
  if (proc.exitCode === null) proc.kill("SIGKILL");
  if (chromiumLog.trim()) console.log("chromium stderr:\n" + chromiumLog.slice(-1200));
}
