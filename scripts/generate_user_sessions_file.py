#!/usr/bin/env python3
"""
generate_palm_sessions.py

Build reproducible, topic-balanced PALM-sourced session lists for SparkMe.

Pipeline
--------
1. Load UBC-NLP/palm (train + test) from Hugging Face.
2. Shuffle deterministically with SEED.
3. Filter to non-MSA + open-ended + the 12 target topics + the 11 target countries.
4. For every (country, topic) pair, build a shard-accessor that hands back
   SHARD_SIZE (13) instances per shard, cycling back through the same pool
   (re-using earlier instances) once the real data for that topic runs out.
5. generate_sessions(country, annotator_id) treats annotator_id as the
   shard id and emits one session per PALM instance in that shard
   (13 sessions x 12 topics = 156 sessions). Each session's first_prompt
   is built from one in-country instance + one randomly-chosen
   out-of-country instance on the same topic.

Out-country-only fallback
-------------------------
Some countries have no open-ended PALM data at all (Lebanon, as of the current
release). For any (country, topic) pair with an empty in-country pool, the
shard is drawn from the *out-of-country* pool for that topic instead (in global
shuffle order, so source countries stay mixed), and first_prompt is built from
the out-country example alone. Such sessions carry "out_country_only": true and
have null in_country_* fields. This keeps the 13 x 12 = 156 session count intact
rather than dropping the topic.

Requirements
------------
    pip install datasets huggingface_hub

PALM is a gated dataset. Before running this script:
    1. Accept the terms at https://huggingface.co/datasets/UBC-NLP/palm
    2. Run `huggingface-cli login` (or set the HF_TOKEN env var)

Usage
-----
    python generate_palm_sessions.py --country "UAE" --annotator-id 8 \
        --out sessions_uae_8.json

    # Just inspect how much data is available per (country, topic):
    python generate_palm_sessions.py --report
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from typing import Dict, List, Optional

try:
    from datasets import load_dataset, concatenate_datasets
except ImportError:
    sys.exit("Missing dependency. Run: pip install datasets huggingface_hub")


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

TOPICS = [
    "Celebrations", "Environment Life", "Flora", "Food", "History", "Literature",
    "Local Geography", "Politics", "Proverbs", "Religion", "Sports", "Travel",
]

COUNTRIES = [
    "Egypt", "Jordan", "Morocco", "Palestine", "Saudi Arabia", "Sudan",
    "Syria", "Tunisia", "UAE", "Yemen", "Algeria", "Lebanon",
]

_TOPIC_LOOKUP = {t.lower(): t for t in TOPICS}
_COUNTRY_LOOKUP = {c.lower(): c for c in COUNTRIES}

FIRST_PROMPT_TEMPLATE = (
    '(in-country example) "{in_country}" OR (out-country example) "{out_country}"'
)

# Used when a (country, topic) pair has no in-country open-ended PALM data.
OUT_COUNTRY_ONLY_FIRST_PROMPT_TEMPLATE = '(out-country example) "{out_country}"'


# --------------------------------------------------------------------------
# Step 1-3: load, shuffle, filter
# --------------------------------------------------------------------------

def load_filtered_palm(seed: int) -> List[dict]:
    """Load PALM, shuffle deterministically, keep only open-ended rows whose
    topic/country are in our target lists. Returns plain dicts (easier to
    shard / json-dump than a HF Dataset)."""

    try:
        raw = load_dataset("UBC-NLP/palm")  # DatasetDict: 'train' + 'test'
    except Exception as e:
        sys.exit(
            "Failed to load UBC-NLP/palm. This is a gated dataset — make sure "
            "you've accepted the terms at "
            "https://huggingface.co/datasets/UBC-NLP/palm and are logged in "
            f"(`huggingface-cli login`).\n\nOriginal error: {e}"
        )

    tagged_splits = []
    for split_name, split_ds in raw.items():
        split_ds = split_ds.add_column("palm_split", [split_name] * len(split_ds))
        tagged_splits.append(split_ds)

    full = concatenate_datasets(tagged_splits)
    full = full.shuffle(seed=seed)  # reproducible order, requirement #2

    records = []
    for row in full:
        topic = _TOPIC_LOOKUP.get(str(row.get("topic", "")).strip().lower())
        country = _COUNTRY_LOOKUP.get(str(row.get("country", "")).strip().lower())
        question_type = str(row.get("question_type", "")).strip().lower()
        variety = str(row.get("variety", "")).strip().lower()

        if question_type != "open-ended" or variety == "msa" or topic is None or country is None:
            continue

        records.append({
            "palm_id": str(row["id"]),
            "palm_split": row["palm_split"],
            "country": country,
            "topic": topic,
            "instruction": row["instruction"],
        })

    return records


# --------------------------------------------------------------------------
# Step 4: pools + shard access (with repeat-on-exhaustion)
# --------------------------------------------------------------------------

def build_pools(records: List[dict]) -> Dict[str, Dict[str, List[dict]]]:
    """pools[country][topic] -> list of that country/topic's instances, in
    the order they came out of the global reproducible shuffle."""
    pools: Dict[str, Dict[str, List[dict]]] = {
        c: {t: [] for t in TOPICS} for c in COUNTRIES
    }
    for r in records:
        pools[r["country"]][r["topic"]].append(r)
    return pools


def build_topic_pools(records: List[dict]) -> Dict[str, List[dict]]:
    """topic_pools[topic] -> every country's instances for that topic, kept in
    global shuffle order. Used to build out-country-only shards so that the
    source countries stay interleaved instead of grouped by country."""
    topic_pools: Dict[str, List[dict]] = {t: [] for t in TOPICS}
    for r in records:
        topic_pools[r["topic"]].append(r)
    return topic_pools


def out_country_pool(topic_pools: Dict[str, List[dict]], country: str,
                     topic: str) -> List[dict]:
    """Every instance on `topic` that is NOT from `country`, in global shuffle
    order."""
    return [r for r in topic_pools[topic] if r["country"] != country]


def get_shard(pool: List[dict], shard_id: int, shard_size: int) -> List[dict]:
    """Return `shard_size` instances for shard `shard_id`. Cycles back to
    the start of `pool` (re-using earlier instances) once it runs out, so
    every shard is always exactly `shard_size` long."""
    if not pool:
        return []
    n = len(pool)
    start = shard_id * shard_size
    return [pool[(start + i) % n] for i in range(shard_size)]


def print_coverage_report(pools: Dict[str, Dict[str, List[dict]]]) -> None:
    """Diagnostic: how much open-ended data actually exists per (country, topic).
    Useful for catching country-name / topic-name mismatches early."""
    print(f"{'country':<15}" + "".join(f"{t[:6]:>8}" for t in TOPICS))
    for c in COUNTRIES:
        counts = "".join(f"{len(pools[c][t]):>8}" for t in TOPICS)
        print(f"{c:<15}{counts}")


# --------------------------------------------------------------------------
# Step 5: session generation
# --------------------------------------------------------------------------

def pick_out_of_country(pools: Dict[str, Dict[str, List[dict]]], country: str,
                         topic: str, rng: random.Random) -> dict:
    others: List[dict] = []
    for c in COUNTRIES:
        if c == country:
            continue
        others.extend(pools[c][topic])
    if not others:
        raise ValueError(f"No out-of-country open-ended data available for topic '{topic}'")
    return rng.choice(others)


def generate_sessions(pools: Dict[str, Dict[str, List[dict]]],
                       topic_pools: Dict[str, List[dict]], country: str,
                       annotator_id: int, seed: int, shard_size: int, n_turns_1=4, n_turns_2=8) -> List[dict]:
    if country not in COUNTRIES:
        raise ValueError(f"Unknown country: {country!r}. Must be one of {COUNTRIES}")

    shard_id = annotator_id  # annotator_id IS the shard id
    rng = random.Random(seed)

    sessions = []
    session_counter = 1

    i = 0

    for topic in TOPICS:
        in_pool = pools[country][topic]

        # No in-country open-ended data (e.g. Lebanon): shard the out-country
        # pool instead and build first_prompt from the out-country example only.
        out_country_only = not in_pool
        if out_country_only:
            shard_pool = out_country_pool(topic_pools, country, topic)
            print(f"WARNING: no in-country open-ended data for {country} / {topic} — "
                  f"using out-country-only prompts for this topic.", file=sys.stderr)
        else:
            shard_pool = in_pool

        shard = get_shard(shard_pool, shard_id, shard_size)

        if not shard:
            print(f"WARNING: no open-ended data at all for {country} / {topic} — skipping topic.",
                  file=sys.stderr)
            continue

        for item in shard:
            in_item: Optional[dict]
            if out_country_only:
                in_item = None
                out_item = item
            else:
                in_item = item
                out_item = pick_out_of_country(pools, country, topic, rng)

            in_prompt = in_item["instruction"] if in_item is not None else None
            out_prompt = out_item["instruction"]

            if out_country_only:
                first_prompt = OUT_COUNTRY_ONLY_FIRST_PROMPT_TEMPLATE.format(
                    out_country=out_prompt
                )
            else:
                first_prompt = FIRST_PROMPT_TEMPLATE.format(
                    in_country=in_prompt, out_country=out_prompt
                )

            sessions.append({
                "session_id": str(session_counter),
                "country": country,
                "topic": topic,
                "n_turns": n_turns_2 if ((i % 9) == 0 or (i % 9) == 4) else n_turns_1,
                "out_country_only": out_country_only,
                "first_prompt": first_prompt,
                "in_country_prompt": in_prompt,
                "in_country_prompt_palm_id": in_item["palm_id"] if in_item is not None else None,
                "in_country_prompt_palm_split": in_item["palm_split"] if in_item is not None else None,
                "out_country_prompt": out_prompt,
                "out_country_prompt_palm_id": out_item["palm_id"],
                "out_country_prompt_country": out_item["country"],
                "out_country_prompt_palm_split": out_item["palm_split"],
                "completed": False,
            })
            session_counter += 1
            i += 1

    rng.shuffle(sessions)

    return sessions


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a PALM-sourced session list for one annotator."
    )
    parser.add_argument("--country", help=f"One of: {', '.join(COUNTRIES)}")
    parser.add_argument("--annotator_id", type=int, help="Used directly as the shard id.")
    parser.add_argument("--batch_sizes", type=str, help="To specify how many sessions in each batch, e.g., `[10, 20, 30, -1]` means batch 1 contains 10 sessions, batch 2 contains 20 sessions, batch 3 contains 30 sessions, batch 4 contains the rest of the sessions for this annotator.")
    parser.add_argument("--out_dir", default=None, help="Output JSON path (defaults to stdout).")
    parser.add_argument("--seed", default=42, type=int, help="Random seed for everything.")
    parser.add_argument("--shard_size", default=13, type=int, help="PALM in-country instances per topic, per shard (= per annotator). Data at index i in that shard is specified to be 4 turns, unless i mod 9 equals 0 or 4 then it is specified to be 8 turns. This roughly gives 4 turns : 8 turns 7:2 proportion.")
    parser.add_argument("--report", action="store_true", help="Print (country, topic) coverage counts and exit.")
    args = parser.parse_args()

    records = load_filtered_palm(args.seed)
    pools = build_pools(records)
    topic_pools = build_topic_pools(records)

    if args.report:
        print_coverage_report(pools)
        return

    if args.country is None or args.annotator_id is None:
        parser.error("--country and --annotator-id are required unless --report is given.")

    sessions = generate_sessions(
        pools, topic_pools, args.country, args.annotator_id,
        args.seed, args.shard_size)

    start_index = 0
    batch_sizes = json.loads(args.batch_sizes)
    print("Batch sizes:", batch_sizes)

    for i, batch_size in enumerate(batch_sizes):
        batch_size = int(batch_size)
        if batch_size != -1:
            end_index = start_index + batch_size
        if batch_size == -1 or end_index > len(sessions):
            end_index = len(sessions)

        output = json.dumps(sessions[start_index:end_index], ensure_ascii=False, indent=2)
        if args.out_dir:
            output_file_path = os.path.join(
                args.out_dir, f"sessions_{args.country}_annotator{args.annotator_id}_batch{i}.json")
            with open(output_file_path, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Wrote {end_index-start_index} sessions to {output_file_path}")

        start_index = end_index
        if start_index == len(sessions):
            print(f"All {len(sessions)} sessions have been used.")
            break


if __name__ == "__main__":
    main()