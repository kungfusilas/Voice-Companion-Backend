"""
Central usage constants for BondAI — no heavy module imports here.
"""

ALLOWANCES: dict[str, dict[str, int]] = {
    "free":    {"msgs": 30,    "voice_secs": 0},
    "basic":   {"msgs": 600,   "voice_secs": 3600},
    "premium": {"msgs": 1500,  "voice_secs": 12000},
    "power":   {"msgs": 3000,  "voice_secs": 30000},
    "elite":   {"msgs": 3000,  "voice_secs": 30000},
}

HOURLY_CAPS: dict[str, int] = {
    "msgs": 60,
    "voice_secs": 1200,
}

# One-time top-up credit packs — sold via Stripe (mode="payment").
# kind must match the column family: "msgs" → topup_msgs, "voice_secs" → topup_voice_seconds.
TOPUP_PACKS: dict[str, dict] = {
    "msgs_500":   {"name": "500 Message Pack",   "amount": 999,   "kind": "msgs",       "credits": 500},
    "msgs_1500":  {"name": "1,500 Message Pack", "amount": 2799,  "kind": "msgs",       "credits": 1500},
    "voice_60":   {"name": "60-Min Voice Pack",  "amount": 899,   "kind": "voice_secs", "credits": 3600},
    "voice_180":  {"name": "180-Min Voice Pack", "amount": 2499,  "kind": "voice_secs", "credits": 10800},
}
