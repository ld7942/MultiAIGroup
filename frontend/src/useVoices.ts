import { useEffect, useState } from "react";
import { systemVoices } from "./speech";

/** 获取浏览器可用的系统音色，并监听异步加载。 */
export function useVoices(): SpeechSynthesisVoice[] {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);

  useEffect(() => {
    const sync = () => setVoices(systemVoices());
    sync();
    window.speechSynthesis?.addEventListener?.("voiceschanged", sync);
    return () => window.speechSynthesis?.removeEventListener?.("voiceschanged", sync);
  }, []);

  return voices;
}
