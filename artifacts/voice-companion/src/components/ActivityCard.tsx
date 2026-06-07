import { useState, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { CheckCircle, XCircle, HelpCircle } from "lucide-react";
import { saveActivityResult } from "@/lib/api";
import type { ActivityData, WordGameActivity, TriviaActivity, WouldYouRatherActivity } from "@/lib/api";

interface ActivityCardProps {
  activity: ActivityData;
  userId: string;
  nsfw: boolean;
  onChatContinue?: (message: string) => void;
}

// ── Shared header ─────────────────────────────────────────────────────────────

function CardHeader({ activity, label, icon }: { activity: ActivityData; label: string; icon: string }) {
  const avatarSlug = activity.companion_id.replace("companion-", "");
  return (
    <div className="flex items-center gap-2 px-3 py-2.5 border-b border-white/6">
      <img
        src={`/companion/avatars/${avatarSlug}.jpg`}
        alt={activity.companion_name}
        className="w-7 h-7 rounded-full object-cover object-top flex-shrink-0"
      />
      <span className="text-xs text-white/60 font-medium">{activity.companion_name}</span>
      <span className="ml-auto text-[11px] text-white/40 flex items-center gap-1">
        <span>{icon}</span>{label}
      </span>
    </div>
  );
}

function Intro({ text }: { text: string }) {
  return (
    <p className="px-3 py-2.5 text-sm text-white/80 leading-relaxed border-b border-white/6">
      {text}
    </p>
  );
}

// ── Word Game ─────────────────────────────────────────────────────────────────

type WGPhase = "clue1" | "clue2" | "clue3" | "won" | "lost";

function WordGameCard({
  activity,
  userId,
  onChatContinue,
}: {
  activity: WordGameActivity;
  userId: string;
  onChatContinue?: (msg: string) => void;
}) {
  const [phase, setPhase] = useState<WGPhase>("clue1");
  const [guess, setGuess] = useState("");
  const [shake, setShake] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const clues = [activity.clue1, activity.clue2, activity.clue3];
  const clueIndex = phase === "clue1" ? 0 : phase === "clue2" ? 1 : phase === "clue3" ? 2 : 2;
  const visibleClues = clues.slice(0, clueIndex + 1);
  const done = phase === "won" || phase === "lost";

  const checkGuess = () => {
    const g = guess.trim().toLowerCase();
    if (!g) return;
    if (g === activity.answer.toLowerCase()) {
      setPhase("won");
      saveActivityResult(userId, activity.companion_id, "word_game", "won");
      onChatContinue?.(`I got it! The word was "${activity.answer}" — that was fun! 🎉`);
    } else {
      setShake(true);
      setTimeout(() => setShake(false), 500);
      setGuess("");
      if (phase === "clue1") setPhase("clue2");
      else if (phase === "clue2") setPhase("clue3");
      else {
        setPhase("lost");
        saveActivityResult(userId, activity.companion_id, "word_game", "lost");
        onChatContinue?.(`I give up... the word was "${activity.answer}". You got me this time!`);
      }
    }
  };

  return (
    <div className="p-3 space-y-2">
      {/* Clues */}
      <div className="space-y-1.5">
        {visibleClues.map((clue, i) => (
          <motion.div
            key={i}
            initial={i > 0 ? { opacity: 0, y: -4 } : false}
            animate={{ opacity: 1, y: 0 }}
            className="flex gap-2 items-start text-sm"
          >
            <span className="text-emerald-400/70 font-mono text-xs mt-0.5 w-12 shrink-0">
              Clue {i + 1}
            </span>
            <span className="text-white/80">{clue}</span>
          </motion.div>
        ))}
      </div>

      {/* Result or input */}
      {phase === "won" && (
        <div className="flex items-center gap-2 text-emerald-400 text-sm pt-1">
          <CheckCircle className="w-4 h-4" />
          <span>Correct! The word was <strong>{activity.answer}</strong>.</span>
        </div>
      )}
      {phase === "lost" && (
        <div className="flex items-center gap-2 text-red-400 text-sm pt-1">
          <XCircle className="w-4 h-4" />
          <span>The word was <strong>{activity.answer}</strong>. Better luck next time!</span>
        </div>
      )}
      {!done && (
        <motion.div
          animate={shake ? { x: [-4, 4, -4, 4, 0] } : {}}
          transition={{ duration: 0.3 }}
          className="flex gap-2 pt-1"
        >
          <input
            ref={inputRef}
            value={guess}
            onChange={(e) => setGuess(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && checkGuess()}
            placeholder="Your guess…"
            className="flex-1 text-sm bg-white/5 border border-white/10 rounded-xl px-3 py-2 text-white placeholder-white/30 outline-none focus:border-emerald-500/50"
          />
          <button
            onClick={checkGuess}
            className="px-3 py-2 rounded-xl text-sm font-medium bg-emerald-600/30 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/50 transition"
          >
            Check
          </button>
        </motion.div>
      )}
    </div>
  );
}

// ── Trivia ────────────────────────────────────────────────────────────────────

function TriviaCard({
  activity,
  userId,
  onChatContinue,
}: {
  activity: TriviaActivity;
  userId: string;
  onChatContinue?: (msg: string) => void;
}) {
  const [selected, setSelected] = useState<"A" | "B" | "C" | "D" | null>(null);
  const opts = (["A", "B", "C", "D"] as const);

  const pick = (opt: "A" | "B" | "C" | "D") => {
    if (selected) return;
    setSelected(opt);
    const correct = opt === activity.correct;
    saveActivityResult(userId, activity.companion_id, "trivia", correct ? "won" : "lost");
    const text = correct
      ? `I got it right — "${activity.options[opt]}"! Did you know: ${activity.fun_fact}`
      : `I picked "${activity.options[opt]}" but the answer was "${activity.options[activity.correct]}". ${activity.fun_fact}`;
    onChatContinue?.(text);
  };

  return (
    <div className="p-3 space-y-3">
      <p className="text-sm text-white/85 leading-snug">{activity.question}</p>
      <div className="grid grid-cols-2 gap-2">
        {opts.map((opt) => {
          const chosen = selected === opt;
          const correct = opt === activity.correct;
          let cls = "border border-white/10 bg-white/5 text-white/80 hover:bg-white/10";
          if (selected) {
            if (correct) cls = "border-emerald-500/60 bg-emerald-600/20 text-emerald-300";
            else if (chosen) cls = "border-red-500/60 bg-red-600/20 text-red-300";
            else cls = "border-white/5 bg-white/3 text-white/30";
          }
          return (
            <button
              key={opt}
              onClick={() => pick(opt)}
              disabled={!!selected}
              className={`text-left rounded-xl px-3 py-2 text-xs transition ${cls}`}
            >
              <span className="font-mono font-bold mr-1.5">{opt}.</span>
              {activity.options[opt]}
            </button>
          );
        })}
      </div>
      <AnimatePresence>
        {selected && (
          <motion.p
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-xs text-amber-300/80 italic leading-snug"
          >
            💡 {activity.fun_fact}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Would You Rather ──────────────────────────────────────────────────────────

function WouldYouRatherCard({
  activity,
  userId,
  onChatContinue,
}: {
  activity: WouldYouRatherActivity;
  userId: string;
  onChatContinue?: (msg: string) => void;
}) {
  const [chosen, setChosen] = useState<"A" | "B" | null>(null);

  const pick = (opt: "A" | "B") => {
    if (chosen) return;
    setChosen(opt);
    saveActivityResult(userId, activity.companion_id, "would_you_rather", "completed");
    const myOption = opt === "A" ? activity.optionA : activity.optionB;
    onChatContinue?.(
      `I'd rather ${myOption.toLowerCase()}. What about you — why did you pick yours?`,
    );
  };

  const companionOptionText =
    activity.companion_choice === "A" ? activity.optionA : activity.optionB;

  return (
    <div className="p-3 space-y-3">
      <p className="text-xs text-white/40 uppercase tracking-wider">Would you rather…</p>
      <div className="grid grid-cols-2 gap-2">
        {(["A", "B"] as const).map((opt) => {
          const label = opt === "A" ? activity.optionA : activity.optionB;
          const isMine = chosen === opt;
          const isCompanion = activity.companion_choice === opt;
          let cls = "border border-white/10 bg-white/5 text-white/80 hover:bg-white/10";
          if (chosen) {
            if (isMine && isCompanion) cls = "border-violet-500/60 bg-violet-600/20 text-violet-200";
            else if (isMine) cls = "border-sky-500/60 bg-sky-600/20 text-sky-200";
            else if (isCompanion) cls = "border-pink-500/40 bg-pink-600/10 text-pink-300";
            else cls = "border-white/5 text-white/30";
          }
          return (
            <button
              key={opt}
              onClick={() => pick(opt)}
              disabled={!!chosen}
              className={`text-left rounded-xl px-3 py-2.5 text-xs leading-snug transition ${cls}`}
            >
              {label}
              {chosen && isCompanion && (
                <span className="block mt-1 text-[10px] opacity-60">
                  {activity.companion_name}'s pick
                </span>
              )}
              {chosen && isMine && !isCompanion && (
                <span className="block mt-1 text-[10px] opacity-60">Your pick</span>
              )}
            </button>
          );
        })}
      </div>
      <AnimatePresence>
        {chosen && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            className="text-xs text-white/60 italic leading-snug"
          >
            <span className="not-italic font-medium text-white/70">{activity.companion_name}:</span>
            {" "}{activity.companion_reason}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

const TYPE_META: Record<string, { label: string; icon: string; border: string; glow: string }> = {
  word_game:        { label: "Word Game",        icon: "🔤", border: "rgba(52,211,153,0.25)",  glow: "rgba(52,211,153,0.06)"  },
  trivia:           { label: "Trivia",           icon: "🧠", border: "rgba(251,191,36,0.25)",  glow: "rgba(251,191,36,0.06)"  },
  would_you_rather: { label: "Would You Rather", icon: "🤔", border: "rgba(99,102,241,0.25)",  glow: "rgba(99,102,241,0.06)"  },
};

export function ActivityCard({ activity, userId, nsfw, onChatContinue }: ActivityCardProps) {
  const meta = TYPE_META[activity.type] ?? TYPE_META.trivia;

  return (
    <div
      className="w-full max-w-[320px] rounded-2xl overflow-hidden text-left"
      style={{
        background: `rgba(255,255,255,0.04)`,
        border: `1px solid ${meta.border}`,
        boxShadow: `0 4px 20px ${meta.glow}`,
      }}
    >
      <CardHeader activity={activity} label={meta.label} icon={meta.icon} />
      <Intro text={activity.companion_intro} />

      {activity.type === "word_game" && (
        <WordGameCard
          activity={activity as WordGameActivity}
          userId={userId}
          onChatContinue={onChatContinue}
        />
      )}
      {activity.type === "trivia" && (
        <TriviaCard
          activity={activity as TriviaActivity}
          userId={userId}
          onChatContinue={onChatContinue}
        />
      )}
      {activity.type === "would_you_rather" && (
        <WouldYouRatherCard
          activity={activity as WouldYouRatherActivity}
          userId={userId}
          onChatContinue={onChatContinue}
        />
      )}
    </div>
  );
}
