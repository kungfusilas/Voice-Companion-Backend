export function KaiAvatar({ size = 120 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <radialGradient id="kai-bg" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#38bdf8" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#0c4a6e" stopOpacity="0.15" />
        </radialGradient>
        <radialGradient id="kai-skin" cx="50%" cy="40%" r="60%">
          <stop offset="0%" stopColor="#fde8d0" />
          <stop offset="100%" stopColor="#f4c8a0" />
        </radialGradient>
        <clipPath id="kai-circle">
          <circle cx="60" cy="60" r="58" />
        </clipPath>
      </defs>

      <circle cx="60" cy="60" r="58" fill="url(#kai-bg)" />
      <circle cx="60" cy="60" r="58" stroke="#38bdf8" strokeWidth="1.5" strokeOpacity="0.4" />

      <g clipPath="url(#kai-circle)">
        {/* Neck — wider/stronger for male */}
        <rect x="47" y="90" width="26" height="20" rx="5" fill="url(#kai-skin)" />

        {/* Shoulders — broader */}
        <ellipse cx="60" cy="118" rx="44" ry="18" fill="#0a1a2e" />

        {/* Hair base — medium brown, short sides */}
        <ellipse cx="60" cy="52" rx="30" ry="28" fill="#6b4226" />
        {/* Shaved sides */}
        <rect x="30" y="52" width="10" height="22" rx="3" fill="#3a2010" />
        <rect x="80" y="52" width="10" height="22" rx="3" fill="#3a2010" />

        {/* Head — more angular/square jaw for male */}
        <path d="M34 64 Q34 90 40 94 Q50 100 60 100 Q70 100 80 94 Q86 90 86 64 Q86 40 60 38 Q34 40 34 64Z" fill="url(#kai-skin)" />

        {/* Jaw line — stronger */}
        <path d="M40 88 Q50 96 60 97 Q70 96 80 88" stroke="#e8c090" strokeWidth="1" fill="none" opacity="0.3" />

        {/* Hair top — slightly wavy, swept to the side */}
        <path d="M32 56 Q34 34 60 32 Q86 34 88 56 Q80 46 60 44 Q40 46 32 56Z" fill="#6b4226" />
        {/* Hair part / wave */}
        <path d="M38 50 Q50 42 64 44 Q78 46 84 52" fill="#7a5030" />
        {/* Wave texture */}
        <path d="M42 42 Q50 36 62 38 Q72 40 78 46" stroke="#8a6040" strokeWidth="2" fill="none" strokeLinecap="round" />
        <path d="M46 44 Q54 40 64 42" stroke="#9a7050" strokeWidth="1.5" fill="none" strokeLinecap="round" opacity="0.6" />
        {/* Side fade lines */}
        <path d="M31 56 Q31 62 32 68" stroke="#4a2c14" strokeWidth="1" fill="none" opacity="0.5" />
        <path d="M89 56 Q89 62 88 68" stroke="#4a2c14" strokeWidth="1" fill="none" opacity="0.5" />

        {/* Eyebrows — thicker, straighter, more defined */}
        <path d="M42 54 Q50 51 57 53" stroke="#4a2c14" strokeWidth="2.2" strokeLinecap="round" fill="none" />
        <path d="M63 53 Q70 51 78 54" stroke="#4a2c14" strokeWidth="2.2" strokeLinecap="round" fill="none" />

        {/* Eyes — blue-grey, more almond, horizontal */}
        <path d="M42 61 Q50 56.5 58 61 Q50 65 42 61Z" fill="white" />
        <ellipse cx="50" cy="61" rx="4.5" ry="4" fill="#5b8db8" />
        <ellipse cx="50" cy="61" rx="2.8" ry="2.8" fill="#2a4060" />
        <circle cx="51.5" cy="59.5" r="1.1" fill="white" opacity="0.9" />
        <path d="M42 61 Q50 57 58 61" stroke="#2a3040" strokeWidth="0.8" fill="none" />

        <path d="M62 61 Q70 56.5 78 61 Q70 65 62 61Z" fill="white" />
        <ellipse cx="70" cy="61" rx="4.5" ry="4" fill="#5b8db8" />
        <ellipse cx="70" cy="61" rx="2.8" ry="2.8" fill="#2a4060" />
        <circle cx="71.5" cy="59.5" r="1.1" fill="white" opacity="0.9" />
        <path d="M62 61 Q70 57 78 61" stroke="#2a3040" strokeWidth="0.8" fill="none" />

        {/* Nose — straighter, slightly larger */}
        <path d="M58 67 L58 76 Q60 78 62 76 L62 67" stroke="#d4a070" strokeWidth="1.2" strokeLinecap="round" fill="none" />
        <path d="M55 76 Q58 79 60 78 Q62 79 65 76" stroke="#d4a070" strokeWidth="1.2" strokeLinecap="round" fill="none" />

        {/* Lips — natural, fuller lower */}
        <path d="M51 83 Q56 80.5 60 81 Q64 80.5 69 83 Q64 88 60 89 Q56 88 51 83Z" fill="#c97c6a" />
        <path d="M51 83 Q56 81 60 81 Q64 81 69 83" stroke="#a05040" strokeWidth="0.8" fill="none" />
        <path d="M54 83 Q60 81 66 83" stroke="#e4a888" strokeWidth="0.8" fill="none" opacity="0.4" />

        {/* Light stubble / jawline shadow */}
        <ellipse cx="44" cy="85" rx="8" ry="4" fill="#8a5030" opacity="0.12" />
        <ellipse cx="76" cy="85" rx="8" ry="4" fill="#8a5030" opacity="0.12" />
        <ellipse cx="60" cy="92" rx="14" ry="4" fill="#8a5030" opacity="0.1" />

        {/* 5 o'clock hint */}
        <line x1="40" y1="80" x2="40" y2="82" stroke="#6b4226" strokeWidth="0.6" opacity="0.3" />
        <line x1="42" y1="82" x2="42" y2="84" stroke="#6b4226" strokeWidth="0.6" opacity="0.3" />
        <line x1="44" y1="83" x2="44" y2="85" stroke="#6b4226" strokeWidth="0.6" opacity="0.3" />
        <line x1="78" y1="80" x2="78" y2="82" stroke="#6b4226" strokeWidth="0.6" opacity="0.3" />
        <line x1="76" y1="82" x2="76" y2="84" stroke="#6b4226" strokeWidth="0.6" opacity="0.3" />
        <line x1="74" y1="83" x2="74" y2="85" stroke="#6b4226" strokeWidth="0.6" opacity="0.3" />
      </g>
    </svg>
  );
}
