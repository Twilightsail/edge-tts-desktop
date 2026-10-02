import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";

interface Props<T extends string> {
  options: readonly (readonly [T, ReactNode])[];
  value: T | "";
  onChange: (value: T) => void;
  /** pill：分段控件（滑块）；line：标签页（滑动下划线） */
  variant?: "pill" | "accent" | "line";
  className?: string;
}

/** 选项之间有一块会滑动的高亮，类似 iOS 的分段控件。 */
export default function Segmented<T extends string>({ options, value, onChange, variant = "pill", className = "" }: Props<T>) {
  const box = useRef<HTMLDivElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  const [thumb, setThumb] = useState<{ x: number; w: number } | null>(null);
  const [animate, setAnimate] = useState(false);

  const measure = useCallback(() => {
    const el = items.current[options.findIndex((o) => o[0] === value)];
    setThumb(el ? { x: el.offsetLeft, w: el.offsetWidth } : null);
  }, [options, value]);

  useLayoutEffect(measure, [measure]);
  useEffect(() => {
    // 首帧直接就位，之后的切换才有滑动动画
    const id = requestAnimationFrame(() => setAnimate(true));
    const ro = new ResizeObserver(measure);
    if (box.current) ro.observe(box.current);
    return () => { cancelAnimationFrame(id); ro.disconnect(); };
  }, [measure]);

  return (
    <div ref={box} className={`seg-ctl ${variant} ${animate ? "anim" : ""} ${className}`} role="tablist">
      <span className="seg-thumb" style={thumb ? { transform: `translateX(${thumb.x}px)`, width: thumb.w, opacity: 1 } : { opacity: 0 }} />
      {options.map(([v, label], i) => (
        <button key={v} role="tab" aria-selected={v === value} ref={(el) => { items.current[i] = el; }} className={v === value ? "on" : ""} onClick={() => onChange(v)}>
          {label}
        </button>
      ))}
    </div>
  );
}
