export function LunaAvatar({ size = 120 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <radialGradient id="luna-bg" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#a78bfa" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#4c1d95" stopOpacity="0.15" />
        </radialGradient>
        <radialGradient id="luna-skin" cx="50%" cy="45%" r="55%">
          <stop offset="0%" stopColor="#fef0e0" />
          <stop offset="100%" stopColor="#f0d5b0" />
        </radialGradient>
        <clipPath id="luna-circle">
          <circle cx="60" cy="60" r="58" />
        </clipPath>
      </defs>

      <circle cx="60" cy="60" r="58" fill="url(#luna-bg)" />
      <circle cx="60" cy="60" r="58" stroke="#a78bfa" strokeWidth="1.5" strokeOpacity="0.4" />

      <g clipPath="url(#luna-circle)">
        {/* Neck */}
        <rect x="50" y="91" width="20" height="18" rx="4" fill="url(#luna-skin)" />

        {/* Shoulders */}
        <ellipse cx="60" cy="118" rx="38" ry="16" fill="#1a0a2e" />

        {/* Back hair — straight, black, long */}
        <rect x="28" y="40" width="64" height="75" rx="8" fill="#12101e" />

        {/* Head shape */}
        <ellipse cx="60" cy="63" rx="27" ry="30" fill="url(#luna-skin)" />

        {/* Hair top with bangs */}
        {/* Crown hair */}
        <path d="M33 55 Q33 28 60 26 Q87 28 87 55 Q78 44 60 43 Q42 44 33 55Z" fill="#12101e" />
        {/* Side bangs */}
        <path d="M33 55 Q30 62 33 70 Q37 58 40 53Z" fill="#12101e" />
        <path d="M87 55 Q90 62 87 70 Q83 58 80 53Z" fill="#12101e" />
        {/* Straight bangs across forehead */}
        <path d="M36 52 Q48 44 60 43 Q72 44 84 52 Q78 56 60 55 Q42 56 36 52Z" fill="#1a1826" />
        {/* Bang fringe — across eyebrow line */}
        <rect x="35" y="49" width="50" height="10" rx="3" fill="#12101e" />
        {/* Hair highlights */}
        <path d="M52 26 Q54 35 53 43" stroke="#3a3060" strokeWidth="1.5" fill="none" opacity="0.6" />
        <path d="M60 26 Q62 35 61 43" stroke="#3a3060" strokeWidth="1.5" fill="none" opacity="0.6" />
        <path d="M68 26 Q66 35 67 43" stroke="#3a3060" strokeWidth="1.5" fill="none" opacity="0.6" />

        {/* Eyebrows — thin, precise, slightly angled */}
        <path d="M44 57 Q50 55 56 57" stroke="#2a1a3a" strokeWidth="1.6" strokeLinecap="round" fill="none" />
        <path d="M64 57 Q70 55 76 57" stroke="#2a1a3a" strokeWidth="1.6" strokeLinecap="round" fill="none" />

        {/* Eyes — dark brown, almond-shaped */}
        {/* Left */}
        <path d="M43 63 Q50 59 57 63 Q50 67 43 63Z" fill="white" />
        <ellipse cx="50" cy="63" rx="4" ry="4" fill="#2a1a08" />
        <ellipse cx="50" cy="63" rx="2.2" ry="2.2" fill="#0a0808" />
        <circle cx="51.2" cy="61.5" r="1" fill="white" opacity="0.85" />
        {/* Subtle liner */}
        <path d="M43 63 Q50 59.5 57 63" stroke="#12101e" strokeWidth="0.8" fill="none" />
        <path d="M43 63 Q50 66 57 63" stroke="#2a1a3a" strokeWidth="0.5" fill="none" />

        {/* Right */}
        <path d="M63 63 Q70 59 77 63 Q70 67 63 63Z" fill="white" />
        <ellipse cx="70" cy="63" rx="4" ry="4" fill="#2a1a08" />
        <ellipse cx="70" cy="63" rx="2.2" ry="2.2" fill="#0a0808" />
        <circle cx="71.2" cy="61.5" r="1" fill="white" opacity="0.85" />
        <path d="M63 63 Q70 59.5 77 63" stroke="#12101e" strokeWidth="0.8" fill="none" />
        <path d="M63 63 Q70 66 77 63" stroke="#2a1a3a" strokeWidth="0.5" fill="none" />

        {/* Nose — delicate */}
        <path d="M58 70 Q60 76 62 70" stroke="#d4a878" strokeWidth="1.1" strokeLinecap="round" fill="none" />
        <circle cx="57.5" cy="74.5" r="1.2" fill="#d4a878" opacity="0.4" />
        <circle cx="62.5" cy="74.5" r="1.2" fill="#d4a878" opacity="0.4" />

        {/* Lips — soft purple tint */}
        <path d="M53 80 Q56.5 77.5 60 78.5 Q63.5 77.5 67 80 Q63.5 84 60 85 Q56.5 84 53 80Z" fill="#b784a7" />
        <path d="M53 80 Q56.5 78 60 78.5 Q63.5 78 67 80" stroke="#9060a0" strokeWidth="0.7" fill="none" />
        <path d="M56 80 Q60 78 64 80" stroke="#d4a8d0" strokeWidth="0.7" fill="none" opacity="0.5" />

        {/* Star accent near eye — Luna's signature */}
        <path d="M82 50 L83 47 L84 50 L87 51 L84 52 L83 55 L82 52 L79 51Z" fill="#a78bfa" opacity="0.7" />
        <path d="M36 50 L37 48 L38 50 L40 51 L38 52 L37 54 L36 52 L34 51Z" fill="#a78bfa" opacity="0.5" />
      </g>
    </svg>
  );
}
