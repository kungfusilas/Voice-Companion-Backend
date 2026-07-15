"""A/B gate for the canonical extraction prompt (Stage 3c deploy gate).

Runs scripts/ab_corpus.yaml against BOTH prompt variants using the app's real
claude.send_message. Ships only on GATE A (legacy preserved) AND GATE B
(canonical quality) both passing.

Run from artifacts/voice-companion (needs ANTHROPIC_API_KEY — e.g. Replit shell):
    python scripts/ab_prompt_gate.py [--runs 2] [--quick]
--runs repeats the corpus to average LLM nondeterminism; --quick = tier 1 only.
Never imported by the app; pytest covers the pure functions with canned data.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import pathlib
import statistics
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

VALID_CATEGORIES = {"family", "work", "location", "health", "goals", "personality", "history"}


def parse_llm_output(raw: str) -> list | None:
    cleaned = (raw or "").strip()
    if "```" in cleaned:
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else parts[0]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()
    try:
        data = json.loads(cleaned)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, list) else None


def _valid_facts(items: list) -> list[dict]:
    return [f for f in items
            if isinstance(f, dict) and f.get("category") in VALID_CATEGORIES
            and isinstance(f.get("fact"), str) and f["fact"].strip()]


def _valid_canonical(c) -> bool:
    from app.canonical.mapper import map_canonical
    from app.shadow_ledger import sanitize_extraction_canonical
    return map_canonical(sanitize_extraction_canonical(c)) is not None


def _canon_predicate(c) -> str | None:
    from app.canonical import registry
    if isinstance(c, dict) and isinstance(c.get("predicate"), str):
        return registry.canonical_predicate(c["predicate"])
    return None


def compute_metrics(results: list[dict]) -> dict:
    turns = len(results)
    parse_failures = sum(1 for r in results if r["parse_failed"])
    expect = [r for r in results if r["expect_facts"]]
    captured = sum(1 for r in expect if r["facts"])
    traps = [r for r in results if r.get("trap")]
    trap_fp = sum(1 for r in traps if r["facts"])
    all_facts = [f for r in results for f in r["facts"]]
    bearing = [r for r in results if r["facts"]]

    def share(key, default):
        counts: dict = {}
        for f in all_facts:
            k = f.get(key) or default
            counts[k] = counts.get(k, 0) + 1
        total = sum(counts.values()) or 1
        return {k: v / total for k, v in counts.items()}, counts

    cat_share, cat_counts = share("category", "unknown")
    sens_share, sens_counts = share("sensitivity", "none")

    emitted = [f["canonical"] for f in all_facts if "canonical" in f]
    valid = [c for c in emitted if _valid_canonical(c)]
    fact_turns_with_valid = sum(
        1 for r in expect if any("canonical" in f and _valid_canonical(f["canonical"])
                                 for f in r["facts"]))
    gold_turns = [r for r in expect if r.get("gold_predicates")]
    gold_hits = sum(
        1 for r in gold_turns
        if any(_canon_predicate(f.get("canonical")) in r["gold_predicates"]
               for f in r["facts"] if "canonical" in f and _valid_canonical(f["canonical"])))
    no_fact_canonical = sum(
        1 for r in results if not r["expect_facts"]
        for f in r["facts"] if "canonical" in f)

    return {
        "turns": turns, "parse_failures": parse_failures,
        "parse_failure_rate": parse_failures / turns if turns else 0.0,
        "capture_rate": captured / len(expect) if expect else 0.0,
        "trap_fp_rate": trap_fp / len(traps) if traps else 0.0,
        "facts_total": len(all_facts),
        "mean_facts_per_bearing_turn": (len(all_facts) / len(bearing)) if bearing else 0.0,
        "category_share": cat_share, "category_counts": cat_counts,
        "sensitivity_share": sens_share, "sensitivity_counts": sens_counts,
        "canonical_emitted": len(emitted),
        # emitted==0 -> 0.0 (honest: the canonical layer produced nothing), not a vacuous 1.0
        "canonical_validity": (len(valid) / len(emitted)) if emitted else 0.0,
        "canonical_coverage": (fact_turns_with_valid / len(expect)) if expect else 0.0,
        # no gold-labeled turns -> 0.0 (forces the corpus to carry gold labels), not a vacuous 1.0
        "gold_hit_rate": (gold_hits / len(gold_turns)) if gold_turns else 0.0,
        "no_fact_canonical": no_fact_canonical,
    }


def _max_share_shift(old_share, new_share, old_counts, new_counts, floor=3):
    keys = set(old_share) | set(new_share)
    shifts = [abs(old_share.get(k, 0.0) - new_share.get(k, 0.0))
              for k in keys
              if max(old_counts.get(k, 0), new_counts.get(k, 0)) >= floor]
    return max(shifts) if shifts else 0.0


def evaluate_gate_a(old: dict, new: dict) -> list[tuple[str, bool, str]]:
    g = []
    g.append(("parse_failure",
              new["parse_failure_rate"] <= old["parse_failure_rate"] + 0.02
              and new["parse_failure_rate"] <= 0.05,
              f"old={old['parse_failure_rate']:.1%} new={new['parse_failure_rate']:.1%}"))
    g.append(("capture_rate", new["capture_rate"] >= 0.95 * old["capture_rate"],
              f"old={old['capture_rate']:.1%} new={new['capture_rate']:.1%}"))
    # old==0 means legacy extracted nothing at all — ratio is meaningless; treat as neutral
    ratio = (new["mean_facts_per_bearing_turn"] / old["mean_facts_per_bearing_turn"]
             if old["mean_facts_per_bearing_turn"] else 1.0)
    g.append(("mean_facts_ratio", 0.75 <= ratio <= 1.35, f"ratio={ratio:.2f}"))
    cat = _max_share_shift(old["category_share"], new["category_share"],
                           old["category_counts"], new["category_counts"])
    g.append(("category_shift", cat <= 0.15, f"max shift={cat:.1%}"))
    sens = _max_share_shift(old["sensitivity_share"], new["sensitivity_share"],
                            old["sensitivity_counts"], new["sensitivity_counts"])
    g.append(("sensitivity_shift", sens <= 0.15, f"max shift={sens:.1%}"))
    g.append(("trap_fp", new["trap_fp_rate"] <= old["trap_fp_rate"] + 0.10,
              f"old={old['trap_fp_rate']:.1%} new={new['trap_fp_rate']:.1%}"))
    return g


def evaluate_gate_b(new: dict) -> list[tuple[str, bool, str]]:
    return [
        ("canonical_coverage", new["canonical_coverage"] >= 0.90,
         f"{new['canonical_coverage']:.1%} (>=90%)"),
        ("canonical_validity", new["canonical_validity"] >= 0.95,
         f"{new['canonical_validity']:.1%} (>=95%)"),
        ("gold_predicate_hit", new["gold_hit_rate"] >= 0.85,
         f"{new['gold_hit_rate']:.1%} (>=85%)"),
        ("no_fact_canonical", new["no_fact_canonical"] == 0,
         f"count={new['no_fact_canonical']} (==0)"),
    ]


def _lat_stats(latencies: list[float], out_chars: list[float]) -> dict:
    p95_idx = max(0, math.ceil(len(latencies) * 0.95) - 1)   # nearest-rank p95
    return {"avg_s": statistics.mean(latencies),
            "p95_s": sorted(latencies)[p95_idx],
            "avg_out_chars": statistics.mean(out_chars)}


async def _run_variant(turns, system_prompt, max_tokens, label):
    from app import claude
    results, latencies, out_chars = [], [], []
    for t in turns:
        t0 = time.perf_counter()
        raw = await claude.send_message(
            system_prompt=system_prompt, history=[],
            user_message=f"User said: {t['user']}\n\nCompanion replied: {t['reply']}",
            model="claude-haiku-4-5-20251001", max_tokens=max_tokens)
        latencies.append(time.perf_counter() - t0)
        out_chars.append(len(raw or ""))
        items = parse_llm_output(raw)
        results.append({"id": t["id"], "expect_facts": t["expect_facts"],
                        "trap": bool(t.get("trap")),
                        "gold_predicates": t.get("gold_predicates") or [],
                        "parse_failed": items is None,
                        "facts": _valid_facts(items) if items else []})
        print(f"  [{label}] {t['id']}: "
              f"{'PARSE-FAIL' if items is None else str(len(results[-1]['facts'])) + ' facts'}")
    return results, latencies, out_chars


async def main():
    import yaml
    from app import memory_extractor

    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--quick", action="store_true", help="tier 1 only")
    args = ap.parse_args()

    corpus = yaml.safe_load((pathlib.Path(__file__).parent / "ab_corpus.yaml").read_text())["turns"]
    if args.quick:
        corpus = [t for t in corpus if t.get("tier") == 1]
    print(f"corpus: {len(corpus)} turns × {args.runs} run(s) × 2 variants")

    old_all, new_all = [], []
    old_lats, old_chars, new_lats, new_chars = [], [], [], []
    for i in range(args.runs):
        print(f"== run {i + 1}: legacy prompt ==")
        r, lats, chars = await _run_variant(corpus, memory_extractor._CORE_FACTS_SYSTEM, 400, "old")
        old_all += r; old_lats += lats; old_chars += chars
        print(f"== run {i + 1}: canonical prompt ==")
        r, lats, chars = await _run_variant(
            corpus, memory_extractor._CORE_FACTS_SYSTEM + memory_extractor._CORE_FACTS_CANONICAL_ADDON,
            900, "new")
        new_all += r; new_lats += lats; new_chars += chars
    old_lat, new_lat = _lat_stats(old_lats, old_chars), _lat_stats(new_lats, new_chars)

    old_m, new_m = compute_metrics(old_all), compute_metrics(new_all)
    gate_a, gate_b = evaluate_gate_a(old_m, new_m), evaluate_gate_b(new_m)

    print("\n== GATE A: legacy preservation ==")
    for n, ok, d in gate_a:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}: {d}")
    print("== GATE B: canonical quality ==")
    for n, ok, d in gate_b:
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}: {d}")
    print(f"  [report] capture vs gold: old={old_m['capture_rate']:.1%} new={new_m['capture_rate']:.1%}")
    print(f"  [report] latency old avg/p95: {old_lat['avg_s']:.2f}/{old_lat['p95_s']:.2f}s; "
          f"new: {new_lat['avg_s']:.2f}/{new_lat['p95_s']:.2f}s; "
          f"out chars old/new: {old_lat['avg_out_chars']:.0f}/{new_lat['avg_out_chars']:.0f}")

    out = {"ts": datetime.now(timezone.utc).isoformat(), "runs": args.runs,
           "quick": args.quick, "old": old_m, "new": new_m,
           "gate_a": [{"name": n, "ok": ok, "detail": d} for n, ok, d in gate_a],
           "gate_b": [{"name": n, "ok": ok, "detail": d} for n, ok, d in gate_b],
           "latency": {"old": old_lat, "new": new_lat}}
    path = pathlib.Path(__file__).parent / f"ab_results_{datetime.now(timezone.utc):%Y%m%dT%H%M%S}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nresults: {path}")
    if all(ok for _, ok, _ in gate_a) and all(ok for _, ok, _ in gate_b):
        print("GATE: PASS — proceed to first-light (allowlist), then staged percent rollout.")
        return 0
    print("GATE: FAIL — do NOT enroll users. Fallback per spec: separate extraction call (own plan).")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
