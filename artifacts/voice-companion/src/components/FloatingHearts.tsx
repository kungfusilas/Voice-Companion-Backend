import { useState } from "react";
import { createPortal } from "react-dom";
import { motion } from "framer-motion";

interface FloatingHeartsProps {
  count: number;
  onComplete: () => void;
}

const OFFSETS = [-28, 0, 28];

export function FloatingHearts({ count, onComplete }: FloatingHeartsProps) {
  const n = Math.min(Math.max(count, 1), 3);
  const hearts = Array.from({ length: n }, (_, i) => i);
  const [doneCount, setDoneCount] = useState(0);

  const handleDone = () => {
    setDoneCount((d) => {
      const next = d + 1;
      if (next >= n) onComplete();
      return next;
    });
  };

  return createPortal(
    <div className="fixed inset-0 pointer-events-none z-[9999] overflow-hidden">
      {hearts.map((i) => (
        <motion.div
          key={i}
          initial={{ opacity: 0, y: 0, x: OFFSETS[i] ?? 0 }}
          animate={{
            opacity: [0, 0.9, 0.9, 0],
            y: -260,
            x: (OFFSETS[i] ?? 0) + (i % 2 === 0 ? -8 : 8),
          }}
          transition={{
            duration: 1.9,
            delay: i * 0.22,
            ease: [0.25, 0.46, 0.45, 0.94],
          }}
          onAnimationComplete={i === n - 1 ? handleDone : undefined}
          style={{
            position: "fixed",
            bottom: "38%",
            left: "50%",
            marginLeft: -12,
            fontSize: 26,
            lineHeight: 1,
          }}
        >
          ❤️
        </motion.div>
      ))}
    </div>,
    document.body
  );
}
