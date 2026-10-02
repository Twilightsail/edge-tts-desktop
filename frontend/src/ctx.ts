import { createContext, useContext } from "react";
import type { Api } from "./api";
import type { Player } from "./player";
import type { EngineInfo, EngineName, Preferences, Task, Voice, VoiceList } from "./types";

export interface Ctx {
  api: Api;
  notify: (text: string, kind?: "ok" | "err") => void;
  voices: Voice[];
  voiceMap: Map<string, Voice>;
  favorites: string[];
  toggleFavorite: (shortName: string) => Promise<void>;
  prefs: Preferences;
  setPref: <K extends keyof Preferences>(key: K, value: Preferences[K]) => void;
  setPrefs: (p: Preferences) => void;
  player: Player;
  previewVoice: (shortName: string) => Promise<void>;
  previewing: string;
  changed: () => void;
  revision: number;
  event?: Partial<Task>;
  engines: EngineInfo[];
  reloadEngines: () => Promise<void>;
  setEngine: (engine: EngineName) => void;
  openAzureSettings: () => void;
  refreshVoices: (refresh?: boolean) => Promise<VoiceList>;
}

export const AppCtx = createContext<Ctx>(null as unknown as Ctx);
export const useApp = () => useContext(AppCtx);
