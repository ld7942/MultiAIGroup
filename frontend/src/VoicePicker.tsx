import { useId } from "react";
import { useVoices } from "./useVoices";

interface Props {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  title?: string;
}

/** 音色选择器：下拉选择浏览器系统音色，也允许手动填写 VoiceStudio 音色 ID。 */
export default function VoicePicker({
  value,
  onChange,
  placeholder = "选择或填写音色 ID",
  title,
}: Props) {
  const voices = useVoices();
  const listId = useId().replace(/:/g, "");

  return (
    <>
      <input
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        title={title}
      />
      <datalist id={listId}>
        {voices.map((voice) => (
          <option key={voice.voiceURI} value={voice.name}>
            {voice.lang}
          </option>
        ))}
      </datalist>
    </>
  );
}
