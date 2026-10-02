import { writeFileSync } from "node:fs";

/** 通过 WebView2 的远程调试端口连接应用窗口，返回一组驱动界面的小工具。 */
export async function connect(port = 9222) {
  const pages = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const ws = new WebSocket(pages.find((p) => p.type === "page").webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0;
  const pend = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); pend.get(d.id)?.(d); };
  const call = (method, params) => new Promise((res) => { const i = ++id; pend.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = (expression) => call("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })
    .then((d) => (d.result?.exceptionDetails ? "EXC: " + JSON.stringify(d.result.exceptionDetails.exception?.description ?? d.result.exceptionDetails) : d.result?.result?.value));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const shot = async (file) => writeFileSync(file, Buffer.from((await call("Page.captureScreenshot", { format: "png" })).result.data, "base64"));
  /** 设置 React 受控 input/textarea 的值 */
  const type = (selector, value) => ev(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});const proto=el instanceof HTMLTextAreaElement?HTMLTextAreaElement:HTMLInputElement;Object.getOwnPropertyDescriptor(proto.prototype,'value').set.call(el,${JSON.stringify(value)});el.dispatchEvent(new Event('input',{bubbles:true}));return 'ok'})()`);
  /** 按文本点击按钮（可选 selector 限定范围） */
  const click = (text, scope = "body") => ev(`(()=>{const b=[...document.querySelector(${JSON.stringify(scope)}).querySelectorAll('button,[role=tab],.voice-row')].find(x=>x.innerText.trim().includes(${JSON.stringify(text)}));if(!b)return 'NOT FOUND: ${text}';b.click();return 'clicked'})()`);
  return { call, ev, sleep, shot, type, click, close: () => ws.close() };
}
