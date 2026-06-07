export function AriaAvatar({ size = 120 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Glow background */}
      <defs>
        <radialGradient id="aria-bg" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#ff7eb3" stopOpacity="0.35" />
          <stop offset="100%" stopColor="#c0185e" stopOpacity="0.12" />
        </radialGradient>
        <radialGradient id="aria-skin" cx="50%" cy="45%" r="55%">
          <stop offset="0%" stopColor="#fde8d8" />
          <stop offset="100%" stopColor="#f4c9a8" />
        </radialGradient>
        <radialGradient id="aria-cheek" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#f48fb1" stopOpacity="0.5" />
          <stop offset="100%" stopColor="#f48fb1" stopOpacity="0" />
        </radialGradient>
        <clipPath id="aria-circle">
          <circle cx="60" cy="60" r="58" />
        </clipPath>
      </defs>

      {/* Background circle */}
      <circle cx="60" cy="60" r="58" fill="url(#aria-bg)" />
      <circle cx="60" cy="60" r="58" stroke="#f472b6" strokeWidth="1.5" strokeOpacity="0.4" />

      <g clipPath="url(#aria-circle)">
        {/* Neck */}
        <rect x="50" y="91" width="20" height="18" rx="4" fill="url(#aria-skin)" />

        {/* Shoulders / top of body */}
        <ellipse cx="60" cy="118" rx="38" ry="16" fill="#2a0a18" />

        {/* Head */}
        <ellipse cx="60" cy="62" rx="30" ry="34" fill="url(#aria-skin)" />

        {/* Hair — flowing waves, warm blonde */}
        {/* Back hair */}
        <ellipse cx="60" cy="58" rx="32" ry="36" fill="#c9883e" />
        {/* Long side strands */}
        <path d="M30 60 Q22 80 28 105 Q34 105 36 80 Q38 65 32 58Z" fill="#d4944a" />
        <path d="M90 60 Q98 80 92 105 Q86 105 84 80 Q82 65 88 58Z" fill="#d4944a" />
        {/* Wave highlights */}
        <path d="M32 62 Q35 72 33 82 Q36 72 38 62" stroke="#e8b56a" strokeWidth="2" fill="none" opacity="0.6" />
        <path d="M88 62 Q85 72 87 82 Q84 72 82 62" stroke="#e8b56a" strokeWidth="2" fill="none" opacity="0.6" />

        {/* Face on top of hair */}
        <ellipse cx="60" cy="64" rx="26" ry="29" fill="url(#aria-skin)" />

        {/* Hair top — parted center */}
        <path d="M34 50 Q40 30 60 28 Q80 30 86 50 Q74 42 60 41 Q46 42 34 50Z" fill="#c9883e" />
        <path d="M60 28 Q64 35 60 41 Q56 35 60 28Z" fill="#b8742e" />

        {/* Eyebrows — soft arched */}
        <path d="M44 52 Q50 49 56 51" stroke="#a06030" strokeWidth="1.8" strokeLinecap="round" fill="none" />
        <path d="M64 51 Q70 49 76 52" stroke="#a06030" strokeWidth="1.8" strokeLinecap="round" fill="none" />

        {/* Eyes */}
        {/* Left eye */}
        <ellipse cx="50" cy="58" rx="7" ry="5.5" fill="white" />
        <ellipse cx="50" cy="58" rx="4.5" ry="4.5" fill="#6a9fd4" />
        <ellipse cx="50" cy="58" rx="2.8" ry="2.8" fill="#2a4a7a" />
        <circle cx="51.5" cy="56.5" r="1.2" fill="white" opacity="0.9" />
        {/* Lashes */}
        <path d="M43.5 55 Q44 53 44.5 52.5" stroke="#5a3520" strokeWidth="1" strokeLinecap="round" />
        <path d="M44.5 53.5 Q45.5 52 46 51.5" stroke="#5a3520" strokeWidth="1" strokeLinecap="round" />
        <path d="M56 55 Q56.5 53 56.5 52.5" stroke="#5a3520" strokeWidth="1" strokeLinecap="round" />

        {/* Right eye */}
        <ellipse cx="70" cy="58" rx="7" ry="5.5" fill="white" />
        <ellipse cx="70" cy="58" rx="4.5" ry="4.5" fill="#6a9fd4" />
        <ellipse cx="70" cy="58" rx="2.8" ry="2.8" fill="#2a4a7a" />
        <circle cx="71.5" cy="56.5" r="1.2" fill="white" opacity="0.9" />
        <path d="M76.5 55 Q76 53 75.5 52.5" stroke="#5a3520" strokeWidth="1" strokeLinecap="round" />
        <path d="M75.5 53.5 Q74.5 52 74 51.5" stroke="#5a3520" strokeWidth="1" strokeLinecap="round" />
        <path d="M64 55 Q63.5 53 63.5 52.5" stroke="#5a3520" strokeWidth="1" strokeLinecap="round" />

        {/* Nose */}
        <path d="M58 64 Q60 71 62 64" stroke="#d4a080" strokeWidth="1.2" strokeLinecap="round" fill="none" />
        <circle cx="57" cy="70" r="1.5" fill="#d4a080" opacity="0.5" />
        <circle cx="63" cy="70" r="1.5" fill="#d4a080" opacity="0.5" />

        {/* Cheeks */}
        <ellipse cx="44" cy="69" rx="7" ry="4" fill="url(#aria-cheek)" opacity="0.7" />
        <ellipse cx="76" cy="69" rx="7" ry="4" fill="url(#aria-cheek)" opacity="0.7" />

        {/* Lips */}
        <path d="M52 76 Q56 74 60 75 Q64 74 68 76 Q64 80 60 81 Q56 80 52 76Z" fill="#e8929a" />
        <path d="M52 76 Q56 74 60 75 Q64 74 68 76" stroke="#d4606e" strokeWidth="0.8" fill="none" />
        <path d="M55 76 Q60 74.5 65 76" stroke="#f4b8c0" strokeWidth="0.8" fill="none" opacity="0.6" />
      </g>
    </svg>
  );
}
