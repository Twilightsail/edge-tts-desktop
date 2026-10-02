import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./ui";
import { useEscape } from "./useEscape";

/** 阅读随安装包分发的第三方许可声明（由 scripts/gen_notices.py 生成，放在 public/ 下）。 */
export default function NoticesDialog({ onClose }: { onClose: () => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  useEscape(true, onClose);
  useEffect(() => {
    fetch("/third-party-notices.txt")
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setText)
      .catch((e) => setError(`无法读取许可声明：${e.message}`));
  }, []);

  return createPortal(
    <div className="modal-wrap" onClick={onClose}>
      <div className="modal notices-modal" role="dialog" aria-label="开源许可" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2>开源许可与第三方声明</h2>
          <button className="round" aria-label="关闭" onClick={onClose}><Icon name="close" /></button>
        </div>
        <div className="modal-body">
          {error ? <p className="error-text">{error}</p> : text ? <pre className="notices">{text}</pre> : <p className="hint"><span className="spinner" /> 正在加载…</p>}
        </div>
      </div>
    </div>,
    document.body,
  );
}
