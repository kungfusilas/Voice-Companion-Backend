"""Predicate cardinality + sub_key derivation. Extend as new predicates appear."""

# Multi-valued predicates accumulate; each entry is keyed by a field of value_json.
_MULTI: dict[str, str] = {
    "children": "name",
    "pets": "name",
    "hobbies": "name",
}


def cardinality(predicate: str) -> str:
    return "multi" if predicate in _MULTI else "single"  # single is the safe default


def sub_key(predicate: str, value_json: dict) -> str | None:
    field = _MULTI.get(predicate)
    if field is None:
        return None
    return str(value_json.get(field, "")).strip().lower()
