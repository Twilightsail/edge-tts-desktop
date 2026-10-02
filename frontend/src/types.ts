export type Status = "queued" | "running" | "succeeded" | "failed" | "cancelled";

export interface Segment {
  text: string;
  title: string;
  voice?: string;
  rate?: number;
  volume?: number;
  pitch?: number;
}

export type EngineName = "edge" | "azure";

export interface EngineInfo {
  id: EngineName;
  name: string;
  configured: boolean;
  region?: string;
  key_hint?: string;
  usage?: { month: string; chars: number; limit: number }; // Azure 本月用量（本机估算）
}

export interface Preferences {
  engine: EngineName;
  style: string; // Azure 说话风格（如 cheerful），空表示默认
  voice: string;
  rate: number;
  volume: number;
  pitch: number;
  subtitles: boolean;
  subtitle_max_chars: number;
  subtitle_offset_ms: number;
}

export interface SynthesisRequest extends Preferences {
  text: string;
  title: string;
  segments?: Segment[];
  segment_chars?: number;
}

export interface Preset {
  id: string;
  name: string;
  settings: Preferences;
}

export interface ImportedDocument {
  name: string;
  text: string;
  characters: number;
  encoding: string;
  requires_split: boolean;
}

export interface StorageInfo {
  cache_bytes: number;
  task_bytes: number;
  tasks: number;
}

export interface TaskError {
  code: string;
  message: string;
  retryable: boolean;
}

export interface Chapter {
  index: number;
  title: string;
  voice: string;
  status: string;
  cached: boolean;
  duration_seconds: number;
}

export interface Task {
  id: string;
  status: Status;
  request?: SynthesisRequest; // SSE 事件不含 request
  created_at: string;
  updated_at: string;
  stage: string;
  attempt: number;
  audio_bytes: number;
  error: TaskError | null;
  audio_url: string | null;
  subtitles_url: string | null;
  vtt_url: string | null;
  duration_seconds: number;
  segment_total: number;
  segment_completed: number;
  chapters: Chapter[];
}

export interface Voice {
  ShortName: string;
  FriendlyName: string;
  Locale: string;
  LocaleName?: string;
  LocalName?: string; // Azure 提供的本地化名称，如“晓辰”
  StyleList?: string[]; // Azure 支持的说话风格
  SecondaryLocaleList?: string[]; // Azure 多语言音色可读的其他语言
  Gender: string;
  VoiceTag?: { VoicePersonalities?: string[] };
}

export interface VoiceList {
  items: Voice[];
  total: number;
  cached: boolean;
  stale: boolean;
}

export interface TaskPage {
  items: Task[];
  total: number;
  offset: number;
  limit: number;
}

export interface About {
  version: string;
  data_dir: string;
  log_file: string;
  python: string;
  platform: string;
  edge_tts: string;
}
