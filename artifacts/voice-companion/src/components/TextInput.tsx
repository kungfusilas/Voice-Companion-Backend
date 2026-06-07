import { useState, type KeyboardEvent } from "react";
import { Send } from "lucide-react";

interface TextInputProps {
  onSend: (text: string) => void;
  disabled: boolean;
  nsfw: boolean;
}

export function TextInput({ onSend, disabled, nsfw }: TextInputProps) {
  const [value, setValue] = useState("");

  const handleSend = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const ringColor = nsfw ? "focus:ring-red-500/50" : "focus:ring-violet-500/50";

  return (
    <div className="flex items-end gap-2">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKey}
        disabled={disabled}
        placeholder="Type a message…"
        rows={1}
        className={`flex-1 resize-none bg-white/5 border border-white/10 rounded-xl px-3 py-2.5 text-sm text-white placeholder-white/30 outline-none focus:ring-2 ${ringColor} transition-all max-h-32 scrollbar-thin scrollbar-thumb-white/10`}
        style={{ fieldSizing: "content" } as React.CSSProperties}
      />
      <button
        onClick={handleSend}
        disabled={disabled || !value.trim()}
        className="w-9 h-9 rounded-xl bg-white/10 hover:bg-white/20 flex items-center justify-center text-white/70 hover:text-white transition disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <Send className="w-4 h-4" />
      </button>
    </div>
  );
}
