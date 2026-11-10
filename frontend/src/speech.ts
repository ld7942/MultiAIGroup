/** 浏览器本地语音播放：VoiceStudio 返回音频时直接播放，否则回退 Web Speech API。
 *
 * 两个容易踩的坑：
 * 1. Chrome/Edge 的自动播放策略要求页面先有用户手势，否则 speechSynthesis 会静默失败；
 *    `unlockSpeech()` 在用户点击时用一条静音 utterance 完成解锁。
 * 2. 某些浏览器不会触发 utterance.onend（长文本、后台标签页、语音引擎异常），
 *    如果不做看门狗，后端会一直等到超时才推进对局。这里同时做“启动超时”和“时长上限”兜底。
 */

export interface VoiceMessage {
  speech_id: string;
  text: string;
  voice_id?: string;
  role?: string;
  speed?: number;
  provider?: string;
  audio?: string;
  audio_url?: string;
}

export interface SpeechStatus {
  supported: boolean;
  unlocked: boolean;
  voices: number;
  zhVoices: number;
  lastError: string;
  lastSpokenAt: number;
}

let cachedVoices: SpeechSynthesisVoice[] = [];
let unlocked = false;
let audioContext: AudioContext | null = null;
let lastError = "";
let lastSpokenAt = 0;

function refreshVoices() {
  if (typeof window !== "undefined" && window.speechSynthesis) {
    cachedVoices = window.speechSynthesis.getVoices();
  }
}

if (typeof window !== "undefined" && window.speechSynthesis) {
  refreshVoices();
  window.speechSynthesis.onvoiceschanged = refreshVoices;
}

export function systemVoices(): SpeechSynthesisVoice[] {
  refreshVoices();
  return cachedVoices;
}

export function voiceMatching(id: string): SpeechSynthesisVoice | null {
  if (!id) return null;
  refreshVoices();
  const target = id.toLowerCase();
  return (
    cachedVoices.find((v) => v.name.toLowerCase() === target) ||
    cachedVoices.find((v) => v.voiceURI.toLowerCase() === target) ||
    cachedVoices.find((v) => v.name.toLowerCase().includes(target)) ||
    null
  );
}

export function speechSupported(): boolean {
  return typeof window !== "undefined" && !!window.speechSynthesis;
}

/** 是否运行在 Tauri 桌面壳里（WebView2 的语音引擎兼容性不稳定）。 */
export function isTauri(): boolean {
  if (typeof window === "undefined") return false;
  const win = window as any;
  return Boolean(win.__TAURI_INTERNALS__ || win.__TAURI__);
}

/** 当前语音引擎状态，用于设置页与牌桌排查“为什么没有声音”。 */
export function speechStatus(): SpeechStatus {
  refreshVoices();
  return {
    supported: speechSupported(),
    unlocked,
    voices: cachedVoices.length,
    zhVoices: cachedVoices.filter((v) => (v.lang || "").toLowerCase().startsWith("zh")).length,
    lastError,
    lastSpokenAt,
  };
}

/** 在用户手势中调用一次，解除浏览器对自动朗读/自动播放的限制。 */
export function unlockSpeech(): void {
  const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
  if (synth && !unlocked) {
    try {
      const primer = new SpeechSynthesisUtterance(" ");
      primer.volume = 0;
      primer.rate = 2;
      synth.speak(primer);
      synth.resume();
      unlocked = true;
    } catch {
      /* ignore */
    }
  }
  try {
    if (!audioContext) {
      const Ctor = window.AudioContext || (window as any).webkitAudioContext;
      if (Ctor) audioContext = new Ctor();
    }
    audioContext?.resume().catch(() => undefined);
  } catch {
    /* ignore */
  }
}

function estimateMs(text: string, speed = 1): number {
  // 中文朗读约 4-6 字/秒，留足余量；上限 2 分钟。
  return Math.min(120000, 6000 + (text.length * 260) / Math.max(0.5, speed));
}

function speakText(msg: VoiceMessage, finish: () => void) {
  const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
  const text = (msg.text || "").trim();
  if (!synth || !text) {
    finish();
    return;
  }
  try {
    synth.resume();
  } catch {
    /* ignore */
  }
  const speed = Math.min(2, Math.max(0.5, Number(msg.speed) || 1));
  const utterance = new SpeechSynthesisUtterance(text);
  const matched = voiceMatching(msg.voice_id || "");
  if (matched) utterance.voice = matched;
  utterance.lang = matched?.lang || "zh-CN";
  utterance.rate = speed;

  let settled = false;
  let started = false;
  let startTimer: ReturnType<typeof setTimeout> | undefined;
  let maxTimer: ReturnType<typeof setTimeout> | undefined;
  const done = () => {
    if (settled) return;
    settled = true;
    if (startTimer) clearTimeout(startTimer);
    if (maxTimer) clearTimeout(maxTimer);
    finish();
  };
  utterance.onstart = () => {
    started = true;
    lastSpokenAt = Date.now();
    lastError = "";
    if (startTimer) clearTimeout(startTimer);
    // Chrome 的已知问题：长文本会中途暂停，定期 resume。
    try {
      synth.resume();
    } catch {
      /* ignore */
    }
  };
  utterance.onend = done;
  utterance.onerror = (event) => {
    lastError = `speech_error:${(event as any)?.error || "unknown"}`;
    done();
  };
  startTimer = setTimeout(() => {
    if (!started) {
      lastError = synth.getVoices().length ? "speech_not_started" : "no_voice_engine";
      done();
    }
  }, 6000);
  maxTimer = setTimeout(done, estimateMs(text, speed));
  try {
    synth.speak(utterance);
  } catch {
    done();
  }
}

/** 播放一条语音并在结束（或失败）时回调，用于向前端后端回执 speech_done。 */
export function playVoice(msg: VoiceMessage, onDone: () => void): void {
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    onDone();
  };
  if (msg.provider === "system") {
    // 后端已用系统语音本机朗读，这里只需回执。
    finish();
    return;
  }
  unlockSpeech();
  const source = msg.audio || msg.audio_url;
  if (source) {
    const audio = new Audio(source);
    const maxTimer = setTimeout(finish, estimateMs(msg.text || "", msg.speed));
    audio.onended = () => {
      clearTimeout(maxTimer);
      finish();
    };
    audio.onerror = () => {
      clearTimeout(maxTimer);
      speakText(msg, finish);
    };
    audio.play().catch(() => {
      clearTimeout(maxTimer);
      speakText(msg, finish);
    });
    return;
  }
  speakText(msg, finish);
}

/** 配置页试听。 */
export function testVoice(text: string, voiceId: string, speed: number): void {
  unlockSpeech();
  playVoice({ speech_id: "test", text, voice_id: voiceId, speed }, () => undefined);
}
