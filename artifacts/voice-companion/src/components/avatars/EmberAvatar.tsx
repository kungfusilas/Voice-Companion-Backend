export function EmberAvatar({ size = 120 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 120 120" fill="none" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <radialGradient id="ember-bg" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#fbbf24" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#92400e" stopOpacity="0.15" />
        </radialGradient>
        <radialGradient id="ember-skin" cx="50%" cy="40%" r="60%">
          <stop offset="0%" stopColor="#7b4a2a" />
          <stop offset="100%" stopColor="#5c3218" />
        </radialGradient>
        <radialGradient id="ember-cheek" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#c47c3a" stopOpacity="0.5" />
          <stop offset="100%" stopColor="#c47c3a" stopOpacity="0" />
        </radialGradient>
        <clipPath id="ember-circle">
          <circle cx="60" cy="60" r="58" />
        </clipPath>
      </defs>

      <circle cx="60" cy="60" r="58" fill="url(#ember-bg)" />
      <circle cx="60" cy="60" r="58" stroke="#fbbf24" strokeWidth="1.5" strokeOpacity="0.4" />

      <g clipPath="url(#ember-circle)">
        {/* Neck */}
        <rect x="50" y="90" width="20" height="20" rx="4" fill="url(#ember-skin)" />

        {/* Shoulders */}
        <ellipse cx="60" cy="118" rx="38" ry="16" fill="#1a0e06" />

        {/* Natural hair — big, rounded afro silhouette */}
        <ellipse cx="60" cy="48" rx="38" ry="35" fill="#1a0a04" />
        {/* Hair texture — coil highlights */}
        <ellipse cx="44" cy="38" rx="10" ry="12" fill="#241008" />
        <ellipse cx="60" cy="32" rx="12" ry="10" fill="#241008" />
        <ellipse cx="76" cy="38" rx="10" ry="12" fill="#241008" />
        <ellipse cx="34" cy="52" rx="8" ry="10" fill="#1e0e06" />
        <ellipse cx="86" cy="52" rx="8" ry="10" fill="#1e0e06" />
        {/* Curl highlights */}
        <path d="M42 30 Q46 26 50 30" stroke="#3a1a08" strokeWidth="2" fill="none" strokeLinecap="round" />
        <path d="M58 24 Q62 20 66 24" stroke="#3a1a08" strokeWidth="2" fill="none" strokeLinecap="round" />
        <path d="M72 30 Q76 26 80 30" stroke="#3a1a08" strokeWidth="2" fill="none" strokeLinecap="round" />
        <path d="M32 48 Q36 44 40 48" stroke="#3a1a08" strokeWidth="1.5" fill="none" strokeLinecap="round" />
        <path d="M80 48 Q84 44 88 48" stroke="#3a1a08" strokeWidth="1.5" fill="none" strokeLinecap="round" />

        {/* Head */}
        <ellipse cx="60" cy="66" rx="26" ry="29" fill="url(#ember-skin)" />

        {/* Eyebrows — full, defined */}
        <path d="M44 56 Q50 53 56 55" stroke="#2a1208" strokeWidth="2" strokeLinecap="round" fill="none" />
        <path d="M64 55 Q70 53 76 56" stroke="#2a1208" strokeWidth="2" strokeLinecap="round" fill="none" />

        {/* Eyes — warm deep brown */}
        <ellipse cx="50" cy="62" rx="6.5" ry="5" fill="white" />
        <ellipse cx="50" cy="62" rx="4.2" ry="4.2" fill="#3d1c0a" />
        <ellipse cx="50" cy="62" rx="2.5" ry="2.5" fill="#1a0804" />
        <circle cx="51.2" cy="60.5" r="1.1" fill="white" opacity="0.85" />
        {/* Lashes */}
        <path d="M44 59 Q44.5 57 45.5 56" stroke="#1a0804" strokeWidth="1.2" strokeLinecap="round" />
        <path d="M45.5 57.5 Q47 56 48 55.5" stroke="#1a0804" strokeWidth="1.2" strokeLinecap="round" />
        <path d="M55.5 59 Q55.5 57 55 56" stroke="#1a0804" strokeWidth="1.2" strokeLinecap="round" />

        <ellipse cx="70" cy="62" rx="6.5" ry="5" fill="white" />
        <ellipse cx="70" cy="62" rx="4.2" ry="4.2" fill="#3d1c0a" />
        <ellipse cx="70" cy="62" rx="2.5" ry="2.5" fill="#1a0804" />
        <circle cx="71.2" cy="60.5" r="1.1" fill="white" opacity="0.85" />
        <path d="M76 59 Q75.5 57 74.5 56" stroke="#1a0804" strokeWidth="1.2" strokeLinecap="round" />
        <path d="M74.5 57.5 Q73 56 72 55.5" stroke="#1a0804" strokeWidth="1.2" strokeLinecap="round" />
        <path d="M64.5 59 Q64.5 57 65 56" stroke="#1a0804" strokeWidth="1.2" strokeLinecap="round" />

        {/* Nose — broader, natural */}
        <path d="M57 68 Q60 75 63 68" stroke="#4a2810" strokeWidth="1.3" strokeLinecap="round" fill="none" />
        <path d="M54 73 Q57 76 60 75 Q63 76 66 73" stroke="#4a2810" strokeWidth="1" strokeLinecap="round" fill="none" />

        {/* Cheek warmth */}
        <ellipse cx="43" cy="71" rx="7" ry="4" fill="url(#ember-cheek)" opacity="0.6" />
        <ellipse cx="77" cy="71" rx="7" ry="4" fill="url(#ember-cheek)" opacity="0.6" />

        {/* Lips — warm terracotta */}
        <path d="M52 79 Q56 76.5 60 77.5 Q64 76.5 68 79 Q64 84 60 85 Q56 84 52 79Z" fill="#c47c5a" />
        <path d="M52 79 Q56 77 60 77.5 Q64 77 68 79" stroke="#a05030" strokeWidth="0.8" fill="none" />
        <path d="M55 79 Q60 77 65 79" stroke="#e4a880" strokeWidth="0.8" fill="none" opacity="0.5" />

        {/* Gold earring hint */}
        <circle cx="33" cy="74" r="3" fill="#fbbf24" opacity="0.8" />
        <circle cx="87" cy="74" r="3" fill="#fbbf24" opacity="0.8" />
      </g>
    </svg>
  );
}
