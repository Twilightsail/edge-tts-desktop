import { useEffect, useRef } from "react";

// 最近打开的层最先关闭：同时开着弹窗和面板时，按一次 Esc 只关最上面的那个。
const stack: { fn: () => void }[] = [];

if (typeof window !== "undefined") {
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.defaultPrevented || !stack.length) return;
    e.preventDefault();
    stack[stack.length - 1].fn();
  });
}

export function useEscape(active: boolean, close: () => void) {
  const latest = useRef(close);
  latest.current = close;
  useEffect(() => {
    if (!active) return;
    const entry = { fn: () => latest.current() };
    stack.push(entry);
    return () => {
      const i = stack.indexOf(entry);
      if (i >= 0) stack.splice(i, 1);
    };
  }, [active]);
}
