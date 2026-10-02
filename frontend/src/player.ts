import { useCallback, useEffect, useRef, useState } from "react";

export interface PlayerState { id: string; playing: boolean; time: number; duration: number; rate: number }

export interface Player extends PlayerState {
  /** 播放/暂停；id 变化时通过 load 取得音频 Blob（同一 id 只加载一次）。 */
  toggle: (id: string, load: () => Promise<Blob>) => Promise<void>;
  seek: (fraction: number) => void;
  cycleRate: () => void;
  forget: (id: string) => void;
}

const RATES = [1, 1.5, 2];

export function usePlayer(): Player {
  const audio = useRef<HTMLAudioElement | null>(null);
  if (!audio.current) audio.current = new Audio();
  const urls = useRef(new Map<string, string>());
  const [state, setState] = useState<PlayerState>({ id: "", playing: false, time: 0, duration: 0, rate: 1 });

  useEffect(() => {
    const a = audio.current!;
    const sync = () =>
      setState((s) => ({ ...s, playing: !a.paused, time: a.currentTime, duration: isFinite(a.duration) ? a.duration : s.duration }));
    const events = ["play", "pause", "ended", "timeupdate", "loadedmetadata"];
    events.forEach((e) => a.addEventListener(e, sync));
    const map = urls.current;
    return () => {
      events.forEach((e) => a.removeEventListener(e, sync));
      a.pause();
      map.forEach((u) => URL.revokeObjectURL(u));
      map.clear();
    };
  }, []);

  const toggle = useCallback(
    async (id: string, load: () => Promise<Blob>) => {
      const a = audio.current!;
      if (state.id === id && a.src) {
        if (a.paused) await a.play();
        else a.pause();
        return;
      }
      let url = urls.current.get(id);
      if (!url) {
        url = URL.createObjectURL(await load());
        urls.current.set(id, url);
      }
      a.src = url;
      a.playbackRate = state.rate;
      setState((s) => ({ ...s, id, time: 0, duration: 0 }));
      await a.play();
    },
    [state.id, state.rate],
  );

  const seek = useCallback((f: number) => {
    const a = audio.current!;
    if (isFinite(a.duration)) a.currentTime = Math.max(0, Math.min(1, f)) * a.duration;
  }, []);

  const cycleRate = useCallback(() => {
    const next = RATES[(RATES.indexOf(state.rate) + 1) % RATES.length];
    audio.current!.playbackRate = next;
    setState((s) => ({ ...s, rate: next }));
  }, [state.rate]);

  const forget = useCallback((id: string) => {
    const url = urls.current.get(id);
    if (!url) return;
    const a = audio.current!;
    if (a.src === url) {
      a.pause();
      a.removeAttribute("src");
      setState((s) => ({ ...s, id: "", playing: false, time: 0 }));
    }
    URL.revokeObjectURL(url);
    urls.current.delete(id);
  }, []);

  return { ...state, toggle, seek, cycleRate, forget };
}
