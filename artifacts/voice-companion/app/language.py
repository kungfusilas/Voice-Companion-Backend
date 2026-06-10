"""
Shared language-detection and preference utilities.

All components import from here — never duplicate Supabase calls or detection logic.
"""
from __future__ import annotations

import os
import re
import logging
import httpx

logger = logging.getLogger(__name__)

# BCP-47 code → display name (used in prompt instructions and log messages)
LANG_NAMES: dict[str, str] = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "ru": "Russian",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "ar": "Arabic",
    "hi": "Hindi", "tr": "Turkish", "pl": "Polish", "sv": "Swedish",
    "da": "Danish", "no": "Norwegian", "fi": "Finnish", "he": "Hebrew",
    "id": "Indonesian", "ms": "Malay", "th": "Thai", "vi": "Vietnamese",
}

# Explicit language-switch request patterns → (regex, BCP-47 code)
_EXPLICIT_SWITCHES: list[tuple[str, str]] = [
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+spanish\b", "es"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+french\b", "fr"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+german\b", "de"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+italian\b", "it"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+portuguese\b", "pt"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+dutch\b", "nl"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+russian\b", "ru"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+japanese\b", "ja"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+korean\b", "ko"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+chinese\b", "zh"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+arabic\b", "ar"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+hindi\b", "hi"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+turkish\b", "tr"),
    (r"\b(?:speak|talk|write|respond|reply|answer)\s+(?:to me\s+)?in\s+english\b", "en"),
    # Native-language requests
    (r"\b(?:habla|escríbeme|responde)\s+(?:en\s+)?español\b|\ben\s+español\b", "es"),
    (r"\b(?:parle|réponds|écris)\s+(?:en\s+)?français\b|\ben\s+français\b", "fr"),
    (r"\bauf\s+deutsch\b|\bsprich\s+deutsch\b|\bschreib(?:e)?\s+(?:mir\s+)?auf\s+deutsch\b", "de"),
    (r"\b(?:parla|rispondi|scrivi)\s+(?:in\s+)?italiano\b|\bin\s+italiano\b", "it"),
    (r"\bem\s+português\b|\b(?:fala|responde|escreve)\s+(?:em\s+)?português\b", "pt"),
    (r"日本語で(?:話して|書いて|答えて)", "ja"),
    (r"한국어로\s*(?:말해|써|답해)", "ko"),
    (r"用中文(?:说|写|回答)", "zh"),
    (r"\bпо-русски\b|\bна\s+русском\b", "ru"),
    (r"\bبالعربية\b|\bبالعربي\b", "ar"),
]

# Non-Latin Unicode script ranges → lang code (checked first; very reliable)
_SCRIPT_RANGES: list[tuple[str, str, str]] = [
    ("\u4e00", "\u9fff", "zh"),   # CJK Unified Ideographs
    ("\u3040", "\u30ff", "ja"),   # Hiragana + Katakana
    ("\uac00", "\ud7af", "ko"),   # Hangul
    ("\u0600", "\u06ff", "ar"),   # Arabic
    ("\u0900", "\u097f", "hi"),   # Devanagari (Hindi)
    ("\u0400", "\u04ff", "ru"),   # Cyrillic
    ("\u0e00", "\u0e7f", "th"),   # Thai
    ("\u05d0", "\u05ea", "he"),   # Hebrew
]

# Common stopwords per Latin-script language (lightweight; ≥2 hits = confident)
# Keep lists broad enough to catch short conversational messages (5–15 words).
_STOPWORDS: dict[str, list[str]] = {
    "es": [
        "que", "de", "no", "una", "es", "en", "lo", "las", "los", "del", "se", "un", "por",
        "con", "para", "pero", "más", "como", "muy", "bien", "hay", "todo", "también", "me",
        "mi", "yo", "el", "la", "al", "le", "su", "si", "ya", "cuando", "tengo", "tiene",
        "hola", "estoy", "estás", "están", "gracias",
    ],
    "fr": [
        "que", "de", "je", "les", "des", "le", "en", "du", "un", "une", "est", "pas", "il",
        "vous", "nous", "mais", "avec", "pour", "dans", "sur", "bien", "aussi", "très", "mon",
        "ma", "bonjour", "merci", "oui", "non", "ce", "cette", "si", "tout", "quand",
    ],
    "de": [
        "ich", "die", "das", "und", "ist", "nicht", "ein", "eine", "mit", "der", "aber",
        "auch", "für", "auf", "sie", "haben", "wird", "mir", "dir", "wir", "ihr", "ja",
        "nein", "gut", "sehr", "wenn", "dann", "was", "wie", "bin", "bist", "hallo", "danke",
    ],
    "it": [
        "che", "di", "non", "una", "il", "la", "un", "per", "ho", "sono", "con", "mi", "ma",
        "dal", "dei", "anche", "questa", "tutto", "bene", "molto", "grazie", "sì", "ciao",
        "come", "quando", "hai", "ha", "voglio", "buongiorno", "salve",
    ],
    "pt": [
        "que", "de", "não", "uma", "em", "um", "para", "com", "por", "mas", "mais", "como",
        "seu", "sua", "isso", "está", "bem", "muito", "obrigado", "olá", "oi", "quando",
        "também", "me", "meu", "minha", "ele", "ela", "sim",
    ],
    "nl": [
        "de", "het", "een", "van", "ik", "je", "we", "ze", "dit", "niet", "zijn", "maar",
        "ook", "bij", "naar", "hebben", "wordt", "goed", "hallo", "ja", "nee", "heel",
        "mijn", "jouw", "hij", "zij", "wat", "hoe", "als",
    ],
    "sv": [
        "och", "att", "det", "en", "är", "på", "av", "för", "med", "som", "inte", "om",
        "ett", "men", "till", "han", "var", "bra", "hej", "ja", "nej", "när", "jag", "du",
        "vi", "de", "här", "där",
    ],
    "pl": [
        "że", "się", "nie", "na", "to", "jest", "jak", "czy", "ale", "już", "przez", "tego",
        "tym", "go", "jej", "być", "tak", "bardzo", "dobrze", "dzień", "cześć", "dziękuję",
    ],
    "tr": [
        "bir", "bu", "de", "da", "ve", "ile", "için", "ben", "sen", "biz", "var", "gibi",
        "ama", "daha", "çok", "olan", "iyi", "merhaba", "evet", "hayır", "teşekkür",
    ],
    "id": [
        "yang", "dan", "di", "ini", "itu", "untuk", "dengan", "dari", "tidak", "ada", "kita",
        "bisa", "lebih", "sudah", "akan", "halo", "ya", "baik", "terima", "kasih", "saya",
        "anda", "kami", "mereka",
    ],
}


def detect_language(text: str) -> str | None:
    """
    Lightweight language detection. Returns BCP-47 code or None if uncertain.

    Priority order:
    1. Non-Latin script ranges (fast, highly reliable, ≥3 chars to commit)
    2. Latin-script stopword frequency (≥2 hits required)
    Returns None when shorter than 6 chars or confidence is too low.
    """
    if not text or len(text.strip()) < 6:
        return None

    # Non-Latin script detection
    script_counts: dict[str, int] = {}
    for ch in text:
        for lo, hi, lang in _SCRIPT_RANGES:
            if lo <= ch <= hi:
                script_counts[lang] = script_counts.get(lang, 0) + 1
    if script_counts:
        top = max(script_counts, key=lambda k: script_counts[k])
        if script_counts[top] >= 3:
            return top

    # Latin-script stopword detection
    words = re.findall(r"\b[a-záàâäãåæçéèêëíìîïñóòôöõøœúùûüýÿ]+\b", text.lower())
    if len(words) < 3:
        return None
    word_set = set(words)
    best_lang, best_count = None, 0
    for lang, stops in _STOPWORDS.items():
        count = sum(1 for w in stops if w in word_set)
        if count > best_count:
            best_lang, best_count = lang, count
    return best_lang if best_count >= 2 else None


def detect_explicit_switch(text: str) -> str | None:
    """
    Returns a BCP-47 code if the user explicitly asks to switch languages,
    or None if no explicit request is detected.
    """
    lower = text.lower()
    for pattern, lang in _EXPLICIT_SWITCHES:
        if re.search(pattern, lower):
            return lang
    return None


def _supa_headers() -> dict:
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


async def get_preferred_language(user_id: str) -> str:
    """Fetch preferred_language from profiles. Returns 'en' on any error."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return "en"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                f"{url}/rest/v1/profiles",
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
                params={"id": f"eq.{user_id}", "select": "preferred_language", "limit": "1"},
            )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0].get("preferred_language") or "en"
    except Exception:
        pass
    return "en"


async def set_preferred_language(user_id: str, lang_code: str) -> None:
    """PATCH preferred_language on the user's profile. Fire-and-forget safe."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            await client.patch(
                f"{url}/rest/v1/profiles",
                headers=_supa_headers(),
                params={"id": f"eq.{user_id}"},
                json={"preferred_language": lang_code},
            )
    except Exception as e:
        logger.debug("set_preferred_language failed: %s", e)


def build_language_instruction(preferred_lang: str) -> str:
    """
    Returns the language-awareness system prompt block injected for ALL tiers.
    """
    lang_name = LANG_NAMES.get(preferred_lang, preferred_lang)
    return (
        f"\n\n## Language awareness\n"
        f"Always respond in the same language the user is currently writing in. "
        f"If they write in Spanish, reply in Spanish. If they switch languages mid-conversation, follow immediately and naturally. "
        f"Your full personality — the warmth, wit, emotional depth — must come through in every language, never stilted or translated-sounding.\n"
        f"The user's preferred language is {lang_name}. "
        f"Default to {lang_name} when their input is ambiguous."
    )
