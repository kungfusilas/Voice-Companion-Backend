"""Predicate registry: canonical names, aliases, cardinality, prompt value-shape hints.

Cardinality drives the engine lifecycle:
  single  — one active fact per slot; a new value supersedes the old.
  multi   — many active facts per slot, keyed by sub_key; each entry independent.
  unknown — freeform/unregistered predicate; accumulates and dedups identical
            values but NEVER supersedes a differing value (no destructive
            lifecycle decisions until cardinality is understood). Freeform
            predicates are registry-promotion candidates as traffic reveals them.
"""
from __future__ import annotations

# Multi-valued predicates: predicate -> the value_json field used as the entity key.
_MULTI: dict[str, str] = {
    "children": "name",
    "pets": "name",
    "hobbies": "name",
}

# Single-valued canonical predicates (one current value at a time).
# NOTE: current_trip and therapy_note are here to preserve existing benchmark
# scenarios, which relied on the old "single-by-default" behavior.
_SINGLE: frozenset[str] = frozenset({
    "home_city", "home_country", "employer", "job_title", "partner",
    "marital_status", "birthday", "dietary_restriction", "pronouns",
    "religion", "native_language", "school", "current_trip", "therapy_note",
})

# Raw predicate (as the LLM might emit) -> canonical predicate name.
_ALIASES: dict[str, str] = {
    "city_of_residence": "home_city", "lives_in": "home_city",
    "city": "home_city", "hometown": "home_city",
    "company": "employer", "workplace": "employer",
    "role": "job_title", "title": "job_title",
    "spouse": "partner", "husband": "partner", "wife": "partner",
    "significant_other": "partner",
    "kids": "children", "child": "children",
    "pet": "pets", "hobby": "hobbies",
    "diet": "dietary_restriction", "dietary_restrictions": "dietary_restriction",
}

# Short value-shape hints injected into the extraction prompt (canonical -> hint).
_VALUE_HINTS: dict[str, str] = {
    "home_city": '{"city": str, "state"?: str, "country"?: str}',
    "employer": '{"name": str}',
    "job_title": '{"title": str}',
    "partner": '{"name": str}',
    "children": '{"name": str, "age"?: int}',
    "pets": '{"name": str, "species"?: str}',
    "birthday": '{"date": "YYYY-MM-DD"}',
    "dietary_restriction": '{"restriction": str}',
    "pronouns": '{"pronouns": str}',
}


def canonical_predicate(raw: str) -> str:
    """Resolve an alias to its canonical predicate; unknown predicates pass through."""
    key = (raw or "").strip().lower()
    return _ALIASES.get(key, key)


def cardinality(predicate: str) -> str:
    p = canonical_predicate(predicate)
    if p in _MULTI:
        return "multi"
    if p in _SINGLE:
        return "single"
    return "unknown"


def sub_key(predicate: str, value_json: dict) -> str | None:
    field = _MULTI.get(canonical_predicate(predicate))
    if field is None:
        return None
    return str(value_json.get(field, "")).strip().lower()


def is_registered(predicate: str) -> bool:
    p = canonical_predicate(predicate)
    return p in _MULTI or p in _SINGLE


def value_hint(predicate: str) -> str | None:
    return _VALUE_HINTS.get(canonical_predicate(predicate))
