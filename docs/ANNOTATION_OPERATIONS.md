# Annotation operations guide

How to screen annotator candidates, onboard annotators, assign their sessions, and collect their data. For how the app itself works, see the [root README](../README.md).

**Contact:** Numaan ([@NaumanNaeem](https://github.com/NaumanNaeem)) for server accounts and the server address.

---

## 0. Get server access

Ask Numaan for a user account on the study server, then connect with SSH:

```bash
ssh <your_username>@<server_ip>
```

Two platforms run on that server:

| | Simulation platform (screening) | Data collection platform |
|---|---|---|
| URL | `http://<server_ip>:8000` | `http://<server_ip>:5000` |
| Repo on server | `/home/holy/projects/SparkMe-Simulation/` | `/home/holy/projects/SparkMe/` |
| GitHub | [holylovenia/SparkMe-Simulation](https://github.com/holylovenia/SparkMe-Simulation) | [holylovenia/SparkMe](https://github.com/holylovenia/SparkMe) |
| Username → user ID map | `data/data/users.json` | `data/data/users.json` |

All paths below are relative to the repo folder on the server. The **user ID** is the random key for each account in `users.json` (22 random characters, e.g. `aBcD1234eFgH5678iJkLmN`). Folders are named by user ID, not username. To look one up:

```bash
cat data/data/users.json
```

---

## 1. Screen the candidate (simulation platform)

1. Ask the candidate to register and log in at `http://<server_ip>:8000`.
2. Five practice sessions are generated automatically. Ask them to complete all five.
3. When they're done, read their score (`model1_chosen_pct`) on the server:

   ```bash
   cat /home/holy/projects/SparkMe-Simulation/data/data/<user_id>/user_stats.json
   ```

   ```json
   {
     "sessions": {
       "4": {
         "session_id": "4", "country": "Egypt", "topic": "Fashion", "n_turns": 4,
         "model1_chosen_count": 4, "total_rated_turns": 4,
         "model1_chosen_pct": 100.0, "completed_at": 1778782267.53
       }
     }
   }
   ```

4. Decide whether the candidate goes on to real data collection.
5. Their practice conversations are in `/home/holy/projects/SparkMe-Simulation/data/logs/<user_id>/ratings/`.

---

## 2. Onboard the annotator (data collection platform)

Ask the annotator to register and log in at `http://<server_ip>:5000`. Registration creates their entry in `data/data/users.json`, where you'll find their user ID. They must fill in the demographic survey before they can see any sessions.

---

## 3. Generate their session files

This step uses `scripts/generate_user_sessions_file.py`. It pulls PALM prompts for one country, takes this annotator's share of them (their "shard"), and splits the result into batches you release over time.

### One-time setup

PALM is a gated dataset:

1. Accept the terms at <https://huggingface.co/datasets/UBC-NLP/palm>.
2. Log in with `hf auth login`, or set the `HF_TOKEN` environment variable.

Then create your own environment in your home folder (conda or venv, whichever you prefer). The script only needs these two packages:

```bash
pip install datasets huggingface_hub
```

### Run it

Run from inside `scripts/`, because `python -m` looks for the module in the current folder. `--out_dir` must already exist.

```bash
cd /home/holy/projects/SparkMe/scripts
mkdir -p ~/sessions/uae/annotator1
python -m generate_user_sessions_file \
  --country "UAE" \
  --annotator_id 1 \
  --batch_sizes "[70, 70, 60, -1]" \
  --shard_size 17 \
  --out_dir ~/sessions/uae/annotator1/
```

| Argument | Meaning | Example |
|---|---|---|
| `--country` | Country to pull data for. One of `Egypt`, `Jordan`, `Morocco`, `Palestine`, `Saudi Arabia`, `Sudan`, `Syria`, `Tunisia`, `UAE`, `Yemen`, `Algeria`, `Lebanon` | `"UAE"` |
| `--annotator_id` | Selects which slice of the PALM data this annotator gets. Give each annotator in the same country a different ID, and keep a record of who got which | `1` |
| `--shard_size` | Prompts per topic for this annotator (default 13). Total sessions = 12 topics × shard size | `17` → 204 sessions |
| `--batch_sizes` | Sessions per batch file. `-1` means "all remaining". `"[70, 70, 60, -1]"` gives batches of 70, 70, 60, then the rest | `"[70, 70, 60, -1]"` |
| `--out_dir` | Folder to save the batch files in. **Required**: without it nothing is saved | `~/sessions/uae/annotator1/` |
| `--seed` | Shuffle seed (default 42). Keep the default for reproducibility | `42` |
| `--report` | Print how much data exists per (country, topic), then exit | |

Each batch is saved as `sessions_<country>_annotator<annotator_id>_batch<n>.json`, with `n` counting from 0.

### Reading the output

```
Batch sizes: [70, 70, 60, -1]
Wrote 70 sessions to …/sessions_UAE_annotator1_batch0.json
Wrote 70 sessions to …/sessions_UAE_annotator1_batch1.json
Wrote 60 sessions to …/sessions_UAE_annotator1_batch2.json
Wrote 4 sessions to …/sessions_UAE_annotator1_batch3.json
All 204 sessions have been used.
```

- **`WARNING: no in-country open-ended data for <country> / <topic> — using out-country-only prompts`** (only for some countries): that country has no PALM data of its own for the topic, so its sessions use prompts from other countries. This is expected, and the topic is still included. Lebanon currently has no data of its own for any topic.
- **`Wrote N sessions to …`**: that batch file was saved.
- **`All N sessions have been used.`**: the batches add up to the full set, so nothing was lost.

---

## 4. Assign a batch

The app only reads a file named exactly `user_sessions.json` in the annotator's folder:

```bash
cp ~/sessions/uae/annotator1/sessions_UAE_annotator1_batch0.json \
   /home/holy/projects/SparkMe/data/data/uae/<user_id>/user_sessions.json
chmod 777 /home/holy/projects/SparkMe/data/data/uae/<user_id>/user_sessions.json
```

The folder name is the country the annotator **registered** with, in lower case (`uae`, `morocco`, `lebanon`, …). The `chmod` makes sure the app can read and update the file, whichever user it runs as.

**Releasing the next batch.** When the annotator has finished a batch, rename the current file so it's kept, then copy in the next one the same way:

```bash
cd /home/holy/projects/SparkMe/data/data/uae/<user_id>/
mv user_sessions.json user_sessions_batch0.json
cp ~/sessions/uae/annotator1/sessions_UAE_annotator1_batch1.json user_sessions.json
chmod 777 user_sessions.json
```

Nothing is lost by swapping files. Session IDs are unique across all of an annotator's batches, and their conversations stay in the ratings folder.

---

## 5. Collect the data

| What | Where (under `/home/holy/projects/SparkMe/`) |
|---|---|
| Conversations and ratings | `data/logs/<country_slug>/<user_id>/ratings/<session_id>_<country>_<topic>_<n_turns>.csv` |
| Demographic survey | `data/data/<country_slug>/<user_id>/survey.json` |
| Session list and progress | `data/data/<country_slug>/<user_id>/user_sessions.json` (`completed: true/false`) |

The columns in the ratings CSV are explained in the [root README](../README.md#data-layout). Here is an example `survey.json`:

```json
{
  "gender": "Non-binary", "age": "45-54", "ethnicity": "Native American",
  "education": "No University Degree", "country": "Belgium",
  "lang_english": "Native speaker", "lang_french": "Advanced",
  "lang_msa": "Advanced", "lang_dialect": "Not a speaker",
  "llm_familiarity": "Somewhat familiar", "llm_frequency": "More than once a month",
  "completed_at": 1778830217.95
}
```

**Before you analyse the data:**

- CSVs written before 2026-08-16 have the `rating_cultural` and `rating_fluency` columns swapped. See the root README.
- For annotators registered as **KSA**, the ratings are under `data/logs/saudi_arabia/<user_id>/`, while their survey and session list are under `data/data/ksa/<user_id>/`.
