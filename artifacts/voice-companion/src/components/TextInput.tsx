import { useRef, useEffect, useState, useCallback, type KeyboardEvent } from "react";
import { Send } from "lucide-react";

interface TextInputProps {
  onSend: (text: string) => void;
  disabled: boolean;
  nsfw: boolean;
  placeholder?: string;
  romantic?: boolean;
  initialValue?: string;
}

export function TextInput({ onSend, disabled, nsfw, placeholder, romantic, initialValue }: TextInputProps) {
  const [value, setValue] = useState(initialValue ?? "");

  const buttonRef = useRef<HTMLButtonElement>(null);
  const touchHandledRef = useRef(false);

  useEffect(() => {
    if (initialValue) setValue(initialValue);
  }, [initialValue]);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }, [value, disabled, onSend]);

  useEffect(() => {
    const btn = buttonRef.current;
    if (!btn) return;
    const onTouchStart = (e: TouchEvent) => {
      e.preventDefault();
      touchHandledRef.current = true;
      handleSend();
    };
    const onTouchEnd = (e: TouchEvent) => {
      e.preventDefault();
      setTimeout(() => { touchHandledRef.current = false; }, 500);
    };
    btn.addEventListener("touchstart", onTouchStart, { passive: false });
    btn.addEventListener("touchend",   onTouchEnd,   { passive: false });
    return () => {
      btn.removeEventListener("touchstart", onTouchStart);
      btn.removeEventListener("touchend",   onTouchEnd);
    };
  }, [handleSend]);

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const borderColor = romantic
    ? "border-rose-500/40 focus:ring-rose-500/40"
    : nsfw
    ? "border-white/10 focus:ring-red-500/50"
    : "border-white/10 focus:ring-violet-500/50";

  const bg = romantic ? "bg-rose-950/20" : "bg-white/5";

  return (
    <div className="flex items-end gap-2">
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKey}
        disabled={disabled}
        placeholder={placeholder ?? "Type a message…"}
        rows={1}
        className={`flex-1 resize-none border rounded-xl px-3 py-2.5 text-sm text-white placeholder-white/30 outline-none focus:ring-2 transition-all max-h-32 scrollbar-thin scrollbar-thumb-white/10 ${bg} ${borderColor}`}
        style={{ fieldSizing: "content" } as React.CSSProperties}
      />
      <button
        ref={buttonRef}
        onClick={() => { if (!touchHandledRef.current) handleSend(); }}
        disabled={disabled || !value.trim()}
        className="w-9 h-9 rounded-xl bg-white/10 hover:bg-white/20 flex items-center justify-center text-white/70 hover:text-white transition disabled:opacity-30 disabled:cursor-not-allowed"
      >
        <Send className="w-4 h-4" />
      </button>
    </div>
  );
}
