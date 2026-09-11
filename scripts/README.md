# `scripts/`: operator tools

Run these from the **repo root**. They read `DATA_DIR` / `LOGS_DIR` from `.env`.

| Script | Status | Use it to… | Default mode |
|---|---|---|---|
| `generate_user_sessions_file.py` (+ `.sh`) | **Live** | Build an annotator's session list from PALM | Writes files only if `--out_dir` is given |
| `delete_users.py` | **Live** | Remove test or withdrawn accounts and all their data | **Dry run** (needs `--apply`) |
| `dedup_ratings_csv.py` | **Live** (backfill) | Remove duplicate consecutive turns from old ratings CSVs | ⚠ **Applies** (use `--dry-run` first). Keeps a `.bak` |
| `migrate_user_folders_to_country.py` | One-off | Move the old flat `data/<user_id>` layout to `data/<country>/<user_id>` | ⚠ **Applies** (use `--dry-run` first) |
| `web_interview/` | Upstream, unused | Cloud Run deploy from upstream SparkMe. The study doesn't deploy this way, and the scripts are stale (Python 3.10 image, no `MODEL_NAME_1..6` or OpenRouter/Fanar keys) | — |
| `annotations/` | Upstream, unused | Separate annotation app for the SparkMe paper (coverage and emergence rubrics). Reads `final_logs/` session agendas, which this study never produces | — |

---

## 1. Generate session lists: `generate_user_sessions_file.py`

`generate_user_sessions_file.sh` is an example invocation, meant to be run from inside `scripts/`.

`datasets` and `huggingface_hub` are in `requirements.txt`. You also need access to the gated PALM dataset. Accept the terms on Hugging Face, then run `huggingface-cli login`.

```bash
# See how much open-ended PALM data exists per (country, topic)
python scripts/generate_user_sessions_file.py --report

# Annotator #0 in Lebanon, split into batches of 32, 32, then the rest
mkdir -p out
python scripts/generate_user_sessions_file.py \
    --country "Lebanon" --annotator_id 0 \
    --batch_sizes "[32, 32, -1]" --out_dir out
# → out/sessions_Lebanon_annotator0_batch0.json, …batch1.json, …batch2.json
```

**What it produces.** 12 topics × `--shard_size` (13) = **156 sessions per annotator**, shuffled with `--seed`. Each session has:

- `session_id`: unique across all of that annotator's batches
- `country`, `topic`, `n_turns`: 4, or 8 for roughly 2 in every 9 sessions
- `first_prompt`: an in-country PALM example plus an out-of-country one, shown as a hint
- PALM IDs and splits for traceability
- `completed: false`

**How annotators are split.** `--annotator_id` is the shard index. Two annotators in the same country with different IDs get different PALM prompts, until the pool wraps around. Keep a record of which ID you gave whom.

**Countries with no in-country data.** Lebanon currently has none. For those, the script uses only out-of-country prompts and marks the sessions `"out_country_only": true`.

**Next step.** Put a batch into the annotator's folder:

```bash
cp out/sessions_Lebanon_annotator0_batch0.json \
   "$DATA_DIR/lebanon/<user_id>/user_sessions.json"
```

`<user_id>` is the annotator's key in `DATA_DIR/users.json`, and the folder name is the lower-cased country. To release a later batch, **append** its entries to the existing `user_sessions.json`. Don't replace the file: the `completed` flags live there.

> The generator's country list uses `Saudi Arabia`, while registration uses `KSA`. See "Known issues" in the root README.

---

## 2. Delete users: `delete_users.py`

```bash
python scripts/delete_users.py alice mkcrTvehXXJapJoGv11nQA          # preview
python scripts/delete_users.py --from-file to_delete.txt --apply --archive
```

Accepts usernames or user IDs. It removes the per-country and legacy folders under `DATA_DIR` and `LOGS_DIR`, any annotation files, and the `users.json` entry. `--archive` moves everything to `_deleted_users/<timestamp>/` instead of deleting it.

**Stop the Flask process first.** A session that is still in memory recreates the deleted folders on its next turn.

---

## 3. De-duplicate ratings: `dedup_ratings_csv.py`

Backfill for a fixed bug where one turn could be recorded twice. It collapses consecutive rows with identical `liked_response`. New data doesn't need it: `save_rating_to_csv` now guards against duplicates.

```bash
python scripts/dedup_ratings_csv.py --root "$LOGS_DIR" --dry-run
python scripts/dedup_ratings_csv.py --root "$LOGS_DIR"            # writes .bak files
```

---

## 4. Folder migration: `migrate_user_folders_to_country.py`

One-off. Only needed if some data still uses the old flat `data/<user_id>` layout, for example after restoring an old backup.

```bash
python scripts/migrate_user_folders_to_country.py --dry-run
```
