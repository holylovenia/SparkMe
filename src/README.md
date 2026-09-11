# `src/`: code map

This page says what each part of `src/` does in the **web study** (`python -m src.main_flask`), and which parts are dormant or deprecated. For setup and the operator workflow, see the [root README](../README.md).

**Status legend**

- **Live**: runs on every session or request.
- **Dormant**: imported or constructed at startup, but none of its logic runs. Kept because `InterviewSession` still builds it. Don't delete it without also removing that construction.
- **Deprecated**: nothing calls it. Safe to delete.

---

## The live path in one paragraph

`main_flask.py` authenticates the participant and, on `/api/start-session`, builds one `InterviewSession` per assigned session. Each `InterviewSession` gets its own asyncio loop on its own thread. A user message goes `send_message → UserDummyParticipant.add_user_message → InterviewSession.add_message_to_chat_history`. That call writes the user row to the ratings CSV and notifies the `Interviewer`. The interviewer rebuilds the conversation from the CSV, calls up to 4 LLMs in parallel, and hands the candidates to `present_as_options`, which puts them into the participant's message buffer. The browser polls `/api/get-messages`, shows the candidates, and posts the chosen one to `/api/submit-rating`. That call writes the interviewer row. When the user has taken `max_turns` turns, `trigger_farewell()` lets the in-flight turn be the last one and closes the session.

---

## `main_flask.py` (Live)

Sections, in file order:

| Section | Key functions | Notes |
|---|---|---|
| Config & paths | `get_user_sessions_path`, `get_survey_path` | `get_user_stats_path` is deprecated (unused) |
| Auth | `load_users`, `save_users`, `hash_password`, `login`, `register`, `logout` | Users live in `DATA_DIR/users.json`. Unsalted SHA-256 |
| Session list & completion | `load_user_sessions`, `save_user_sessions`, `mark_user_session_completed`, `sync_completed_sessions` | `completed` is set when `is_session_done` is true in `get_messages` (single source of truth). `sync_completed_sessions` backfills it from the CSV |
| CSV progress | `_read_csv_progress`, `_is_complete_per_csv` | Count user turns and find who spoke last. `_count_completed_user_turns` is deprecated |
| Session lifecycle | `create_interview_session`, `start_session`, `cleanup_old_sessions`, `_shutdown_wrapper_loop` | `start_session` reuses a live session for the same assignment, or rebuilds it from the CSV |
| Chat API (used by `chat.html`) | `send_message`, `get_messages`, `submit_rating`, `acknowledge_messages`, `session_history`, `mark_session_completed` | |
| Resume logic | `_maybe_resume_interviewer`, `_ensure_interviewer_response`, `_has_pending_interviewer_messages` | Re-triggers the interviewer if the CSV shows the user spoke last and no candidates are pending |
| Survey | `survey`, `api_save_survey`, `survey_completed` | Required before `/` is reachable |
| Monitoring | `health` | Unauthenticated |

**Deprecated routes and helpers in `main_flask.py`** (no caller in the live UI):

| Name | Why |
|---|---|
| `/api/send-voice`, `/api/get-voice-response` | Stubs that return 503. Only called by the unused `text_chat.html` / `speech_chat.html` |
| `/process_audio`, `/get_last_messages`, `wait_for_agent_response` | Upstream voice flow. Creates sessions without an assignment |
| `/api/end-session` | Works, but no page calls it. Sessions end by turn count |
| `/api/session-status`, `/api/debug-session` | Debug only. No page calls them |
| Global `loop`, `start_background_loop`, `run_async_task` | Superseded by the per-session loops. The thread still starts but idles |
| `get_user_stats_path`, `_count_completed_user_turns` | Unused |

---

## `interview_session/` (Live)

| File | Status | Role |
|---|---|---|
| `interview_session.py` | Live | `InterviewSession`: owns state flags (`session_in_progress`, `_farewell_done`, `_farewell_rated`, `_session_ending`), the turn counter, CSV writes for user turns, `present_as_options`, `trigger_farewell`, and `run()` (the inactivity-timeout loop) |
| `session_models.py` | Live | `Message`, `MessageType`, `Participant` base class |
| `user/dummy_participant.py` | Live | `UserDummyParticipant`: the web participant. Buffers interviewer messages for polling |
| `user/user.py` | Live (base class) | `User` terminal participant. In web mode only its `__init__` runs (via the subclass) |
| `prompts/conversation_summarize.py` | Dormant | Only called from `_update_conversation_summary` |

Dormant methods inside `InterviewSession`: `_check_and_trigger_report_update` (runs every few turns, but the report update itself is commented out), `_update_conversation_summary`, `final_update_report_and_agenda`, `get_session_memories`, `end_session`, `set_db_session_id` / `get_db_session_id`, and `_setup_signal_handlers` (agent mode only).

---

## `agents/`

| Path | Status | Notes |
|---|---|---|
| `base_agent.py` | Live | `BaseAgent`: retrying, deadline-bounded LLM calls on a dedicated thread pool (`call_engine_async`). **Class variables `token_tracker` / `current_turn` / `use_baseline` are process-wide** |
| `interviewer/interviewer.py` | Live | `_generate_turn` (4 candidates), `_get_prompt`, `get_event_stream_str_from_csv`. `_handle_quantify_response` is deprecated. `_handle_response` is only the single-reply fallback |
| `interviewer/prompts.py`, `interviewer/tools.py` | Dormant | Upstream prompt and tools. The live prompt is built inline in `_get_prompt` |
| `session_scribe/` | Dormant | Constructed but not subscribed to messages. `augment_session_agenda` returns immediately |
| `report_team/` | Dormant | `ReportOrchestrator` is constructed and never invoked |
| `strategic_planner/` | Dormant | Imported. The construction is commented out (`self.strategic_planner = None`) |
| `user/` | Dormant | `UserAgent`, an LLM-simulated interviewee. Only used by `main.py --user_agent` |
| `shared/` | Dormant | Tools and prompts for the agents above |

---

## `utils/`

| Path | Status | Notes |
|---|---|---|
| `data_process.py` | Live | `save_rating_to_csv` (the study data writer, with a duplicate guard). `save_feedback_to_csv` is deprecated. `read_from_pdf` is only used by commented-out code |
| `user_paths.py` | Live | `user_data_dir` / `user_logs_dir`: always use these for per-user paths |
| `llm/engines.py` | Live | `get_engine(model_name)` dispatches on the name prefix. `invoke_engine` normalises responses |
| `llm/models/openrouter.py` | Live | OpenRouter with a quantization fallback (fp16/bf16, then 8-bit, then any) |
| `llm/models/{fanar,jais,gemini_api,openai_next,vllm,deepseek,claude,gemini}.py` | Live if configured | One per provider. Used only if a `MODEL_NAME_*` points to it |
| `llm/models/lipsum.py` | Live (placeholder) | `lipsum:` marks an empty model slot. The interviewer filters it out |
| `llm/xml_formatter.py`, `llm/prompt_utils.py` | Dormant | Used by the dormant agents |
| `logger/session_logger.py` | Live | Writes `execution_logs/session_<id>/*.log`. **`_current_logger` is process-wide** |
| `logger/evaluation_logger.py` | Dormant | Set up per session. Nothing logs to it in web mode |
| `token_tracker.py` | Live | Token usage JSON under `statistics/` |
| `speech/` | Deprecated (web) | STT/TTS. Only reached by `/process_audio` and terminal mode |
| `topic_extractor.py` | Deprecated | Not imported anywhere |
| `text_formatter.py`, `constants/colors.py` | Dormant / cosmetic | |

---

## `content/` (Dormant)

`session_agenda/`, `memory_bank/`, `question_bank/`, `embeddings/`, `report/`: upstream SparkMe state. In web mode, `InterviewSession` only loads these to get a `session_id`, which ends up always being `1`. Nothing reads them afterwards.

---

## `web/`

| File | Status |
|---|---|
| `templates/login.html`, `register.html`, `survey.html`, `sessions.html`, `chat.html` | Live |
| `templates/index.html`, `text_chat.html`, `speech_chat.html` | Deprecated (not rendered by any route) |
| `static/style.css` | Live |

---

## `main.py` (Deprecated)

Upstream terminal and agent entry point. The study doesn't use it, and it hasn't been tested since the interviewer was changed to produce 4 candidates per turn (a terminal user would be prompted once per candidate).

---

## Conventions worth keeping

- **The ratings CSV is the source of truth.** Anything that needs the conversation (prompt, resume, completion) reads the CSV, not in-memory history.
- **CSV dialect**: always `quoting=csv.QUOTE_ALL, escapechar='\\'` for both reading and writing.
- **Per-user paths**: go through `user_paths.user_data_dir` / `user_logs_dir`. Never join `DATA_DIR` and `user_id` by hand.
- **Shared JSON writes**: use `_atomic_write_json` plus a lock (see `mark_user_session_completed`).
- **Two session IDs**: `sel_session_id` is the assignment ID from `user_sessions.json` and names the CSV. `InterviewSession.session_id` is an internal counter used only for log folders.
