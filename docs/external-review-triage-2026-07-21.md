# External Review Triage — 21 July 2026

Three external reviews (via Box) of Project Y / Sahaay. This document triages
every claim against the **live** code in `C:\Users\nande\project-y`, verified at
runtime, and turns what survives into a work plan.

---

## Root cause: Box is stale

**Box `src/core/pipeline.py` = 6,508 bytes. That is byte-identical to the
15 July baseline.** The live file is ~10 KB after seven commits.

The reviewers read code that predates every fix made on 20–21 July. That is why
they report bugs that are already closed — and it will keep happening on every
future review until Box is updated.

**Action 0 (do this first, ~5 minutes): push `project-y` to Box.** Everything
else is downstream of this.

Important: being stale does *not* make the reviews worthless. They caught
several real, serious problems that I had not — see "New and valid" below. Two
of the three reviews are of genuinely high quality.

---

## Verdict summary

| Category | Count |
|---|---|
| Already fixed in live code (stale-tree artifacts) | 9 |
| **Real and outstanding — confirmed at runtime** | 8 |
| **New, valid, and not previously caught by me** | 11 |
| Wrong / not applicable | 2 |

---

## A. Already fixed — no action (reviewers were reading old code)

Verified at runtime today:

| Claim | Evidence it is fixed |
|---|---|
| "System prompt never loads; every call uses the one-line fallback" | `get_prompt("system_prompt.txt")` returns **2,139 chars**, contains `{context_blob}` and `14416`. Fixed in `ebef4bc`. |
| "VAD built and thrown away; no barge-in" | Wired in `5c74445`; `stop_secs` tuned 0.2 → 1.5 for Indian-language pausing. Barge-in confirmed working on a live call. |
| "No pipeline cancellation on hang-up" | `on_client_disconnected` → `task.cancel()` present. |
| "`aiohttp_session` leaks if `runner.run` throws" | Now in `try/finally`. |
| "`src/services/` is an empty package" | Contains `web_search.py`. |
| "No dashboard code exists" | `/dashboard` + `/dashboard/{file}` with per-call JSONL logs. |
| "`server.py` imports 4 unused symbols" | Cleaned; now uses `parse_telephony_websocket`. |
| "Exotel `start` payload is a TODO / will break" | Replaced with pipecat's `parse_telephony_websocket`; real calls connect. |
| "No `.env.example`" | Present. |

---

## B. Real and outstanding — confirmed by runtime test

### B1. Safety is effectively non-functional for Indian users — **P0**

Ran the live `rules.py` against representative inputs:

```
suicide (English)     -> CRISIS -> Tele MANAS      ✓
suicide (Hinglish)    -> NO MATCH                  ✗
suicide (Hindi)       -> NO MATCH                  ✗
suicide (Telugu)      -> NO MATCH                  ✗
heart attack          -> CRISIS -> Tele MANAS      ✗ WRONG LINE
"call my girlfriend"  -> SEXUAL redirect           ✗ false positive
"romantic restaurant" -> SEXUAL redirect           ✗ false positive
```

For a Hindi/Telugu-first product, **vernacular crisis detection does not exist**.
A caller in distress in Hindi or Telugu gets no helpline. Separately, someone
reporting a heart attack is directed to a *mental health* line; `112` is defined
in `config.py` and referenced nowhere.

Also confirmed: `SafetyGuardrailProcessor` forwards the transcript to the LLM
unconditionally and runs checks in a fire-and-forget `create_task`, so unsafe
input reaches the model regardless.

**The fix already exists, unmerged, in `_pending-merge-adr003/`.** Verified
against the same inputs:

```
suicide EN/Hinglish/Hindi/Telugu -> mental_crisis, 14416, suppressLLM=True  ✓
heart attack (EN + Hindi)        -> medical_emergency, 112, suppressLLM=True ✓
girlfriend / romantic restaurant -> NO MATCH  ✓ (false positives gone)
```

Merging it closes vernacular coverage, the medical/mental-health mixup, the
false positives, and LLM suppression in one move. Note it also needs its
`frame.finalized` gate stripped — Sarvam never sets that flag (same bug fixed
in `5c74445`).

### B2. Profile save crashes on datetime — **P0**

Reproduced exactly:

```
save_profile(profile with consent_given_at=datetime.now())
  -> TypeError: Object of type datetime is not JSON serializable
```

And the second-order bug is real too: `CallerProfile(**data)` leaves
`reminders` / `daily_goals` as plain dicts, so `to_context_blob()` will raise
`AttributeError` on the next read. `_pending-merge-adr003/src/memory/memory_store.py`
has `_json_default` + `_profile_from_dict` that fix both.

### B3. All "unknown" callers share one Redis key — **P0 privacy**

```
_key('unknown') -> 'caller::profile'     # shared by every unidentified caller
```

Cross-contamination of facts and rolling summaries between strangers. The
snapshot isolates this (`caller:unknown:ephemeral`, never persisted).

### B4. Phone numbers are not normalized — **P1**

```
_key('9876543210')   -> caller:9876543210:profile
_key('919876543210') -> caller:919876543210:profile   # same person, two profiles
```

Snapshot's `normalize_phone()` (last-10-digits) fixes it.

### B5. `LatencyTracker` records nothing — **P1**

Fifth consecutive call logging `total_turns: 0, avg_latency_ms: 0`. Instrumentation
exists in the snapshot. All audio/endpointing tuning so far has been done blind.

### B6. Onboarding is dead code — **P1**

`handle_onboarding_turn` is never imported by `pipeline.py` or `server.py`.
Note: the current greeting-cue approach partly covers this, so decide
deliberately — **wire it or delete it**, don't leave it ambiguous.

### B7. `reminder_scheduler` is dead, and nothing ever creates a `Reminder` — **P2**

The read path exists; the write path does not. "Reminders" is promised in the
system prompt with no implementation end to end.

### B8. Config never validates `SARVAM_API_KEY` — **P1**

Missing key propagates `None` into four SDKs and fails deep inside a third-party
library instead of at startup.

---

## C. New and valid — reviewers caught these, I had not

These are the reviews' real value. None are stale-tree artifacts.

| # | Finding | Priority |
|---|---|---|
| C1 | **No auth on `/exotel-stream`.** Anyone with the URL can drive a full STT+LLM+TTS call on your Sarvam bill. `EXOTEL_WS_USER`/`PASS` exist in `.env` and are unused. | **P0 (cost/abuse)** |
| C2 | **Negation is unhandled**: "I would never hurt someone" triggers HARM. Confirmed still broken *even in the snapshot*. | P1 |
| C3 | **No TTL on Redis profile keys** — facts persist forever. Direct DPDP retention gap. | P1 |
| C4 | **`memory_enabled` is decorative** — the user-facing memory opt-out is never read anywhere. | P1 (trust) |
| C5 | `start_call()` sits outside the `try/except` in `server.py` — a Redis blip drops the call instead of degrading to a fresh profile. | P1 |
| C6 | `total_minutes` never updated; `free_minutes_per_day` never enforced; `history_turns_kept` never used. Three config values that are pure decoration. | P2 |
| C7 | `requirements.txt` has no upper bounds and mixes dev/test deps into prod. | P2 |
| C8 | `print()` everywhere with no correlation id — concurrent calls will interleave into unreadable logs. | P2 |
| C9 | A fresh `AsyncOpenAI` client is constructed per call (httpx client leak); should be app-scoped. | P2 |
| C10 | `get_soft_redirect()` rebuilds its dict on every call. | P3 |
| C11 | `extract_name_with_llm` is `async` and does zero awaits — pure regex despite the name. | P3 |

Also correct and worth acting on: **`tests/` is effectively dead** — it targets
the *old* guardrails API (`is_emergency`, `contains_sexual_content`) and will
fail on import the moment the snapshot is merged. Both B1 and B2 are exactly the
class of bug one trivial test would have caught.

---

## D. Wrong / not applicable

- **"Fix `prompt_manager` to load `prompts/voice/`"** — already recursive; verified
  loading 2,139 chars at runtime.
- **"`project y 0716.zip` is in the repo"** — it is in `Downloads\AI Phone`, not in
  the `project-y` working tree, and is gitignored.

---

## E. What the reviews could not see

All three reviews are static reads. They missed every bug that only appears when
a call actually runs — the ones found from dashboard transcripts:

- `...` counts as three sentence boundaries, truncating replies mid-thought
  (cost ~58% of one call)
- `polish_for_speech` leaves a dangling leading comma (`", great. What are..."`)
- The model regenerating its previous reply verbatim with correct context
- **Search claiming to run and never running** — the actual cause of "too dumb"
- TTS loudness 1.9 producing measurable clipping

Static review and runtime evidence are catching different bug classes. Keep both.

---

## F. Plan

### Phase 0 — Stop the stale-review loop (5 min)
Push `project-y` to Box. Every future review then targets real code.

### Phase 1 — Safety and data integrity (P0, ~half day)
1. Merge `_pending-merge-adr003` guardrails (`rules.py` + `processor.py`),
   stripping the `frame.finalized` gate. Closes B1 entirely.
2. Add negation handling (C2) — snapshot does not fix it.
3. Merge the snapshot's `memory_store.py`: fixes B2, B3, B4 together.
4. Rewrite `tests/` against the new API; add round-trip and vernacular-crisis
   tests. These two bugs justify the test suite on their own.

### Phase 2 — Security and stability (P0/P1, ~2 hours)
5. WebSocket auth on `/exotel-stream` using the existing `EXOTEL_WS_USER/PASS` (C1).
6. Validate required env vars at startup (B8).
7. Wrap `start_call()` with a fallback to a fresh profile (C5).
8. Merge latency instrumentation (B5) — makes everything measurable.

### Phase 3 — The actual product gap (P0 for value, ~rest of day)
9. Real search backend + never letting the model *claim* to search.
   See `docs/call-analysis-2026-07-21.md`. This is what "too dumb" means.
10. The two small runtime fixes: ellipsis boundary, dangling comma.

### Phase 4 — Privacy and hygiene (P1/P2)
11. Redis TTL (C3); honour `memory_enabled` (C4); expose "forget me".
12. `total_minutes` / free-minutes enforcement / `history_turns_kept` (C6).
13. Pin requirements, split dev deps (C7); `logging` + correlation id (C8);
    app-scoped OpenAI client (C9).
14. Decide onboarding: wire it or delete it (B6). Same for reminders (B7).
15. Real README.

### Answer to the reviewers' question — "which tree is canonical?"
**`C:\Users\nande\project-y`, branch `conversation-quality-and-adr003-snapshot`.**
Box is a stale mirror and should be treated as read-only until Phase 0 is done.

---

## Note on current safety posture

The vernacular safety gap (B1) is live in the code as it stands. All services are
currently stopped, so no calls can reach it. **Phase 1 should land before the next
real test call**, particularly any call with people other than you.
