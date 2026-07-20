# Call Analysis — 21 July 2026, 00:09 (252s, Telugu/Hindi/English)

**Log:** `logs/calls/20260721-000939_9fe16a147a99813a63bbea70cfdc1a7l.jsonl`
**Dashboard:** `/dashboard?k=<DASHBOARD_KEY>`
**Founder verdict:** *"the talking is getting better but the product is too dumb
without valid knowledge."*

This is the work queue for tomorrow. Findings are ordered by impact, and every
claim below was verified against the log or reproduced in code — not inferred.

---

## What is now working (do not regress these)

- **Language switching is solid.** Five switches in one call
  (en → hi → te → hi → te), every explicit request honoured within one turn,
  and it *stayed* switched. This was the top complaint two calls ago.
- **No verbatim self-echo.** The repeat guard added in `9001b19` held.
- **Tone is warm and human.** It played along with a joke, took correction
  gracefully, apologised without grovelling.
- **No clipping complaints** about English/Telugu audio after loudness 1.9 → 1.0.

---

## P0 — It claims to search, and never does

The single most damaging finding, and the direct cause of the founder's verdict.

| Time | What it said |
|------|--------------|
| 61.2s | "Aap live data chahte hain. **Let me check that for you.**" |
| 90.5s | "ఇప్పుడు ఆ ఆరెంజ్ ఎగుమతి గురించి **వివరాలు వెతుకుతున్నాను**" (*I'm searching now*) |

**`NewsInjectProcessor` fired zero times during the entire call.** Verified by
replaying every user utterance through `looks_like_current_events()` — all
returned `False`, including "What are the countries which take most oranges?"
and "you have the live data".

Root cause: the intent regex only covers news / weather / prices / scores. It
was scoped for *current events*, but the caller wanted **research** — export
markets, business process, trade data. Nothing in that space matches.

Compounding it: with no `LIVE SEARCH RESULTS` block present, the prompt's rule
says *"say you could not check"* — but the model instead announced it **was**
checking. So the failure mode is worse than "I don't know": it is a false
promise, and then silence. That reads as broken *and* dishonest.

The orange-export answers it did give (USA/China/Germany as top importers,
phytosanitary certificates) were plausible-sounding model recall with **no
grounding**. For a product whose value is trustworthy answers, unverifiable
confident claims are a liability, not a feature.

**Tomorrow:**
1. Replace narrow intent-matching with a **general knowledge-need detector** —
   any factual/research question, not just news keywords.
2. Google News RSS is the wrong backend for this. Needs a real search API
   (Brave / Tavily / SerpAPI) returning snippets, not headlines.
3. Make "I'm checking" **structurally impossible unless a fetch actually ran** —
   the filler should be emitted by the search processor (it already is), never
   by the model. Add a prompt rule: never claim to search; the system searches.
4. Consider proper tool-calling instead of context injection, so the model
   cannot narrate an action it did not take.

---

## P1 — `polish_for_speech` leaves a dangling leading comma (self-inflicted)

Reproduced exactly:

```
"Sure, great. What are you looking for?"  ->  ", great. What are you looking for?"
"Okay, tell me what you're researching."  ->  ", tell me what you're researching."
"Great, exporting oranges."               ->  ", exporting oranges."
```

Matches the transcript verbatim at 22.5s, 31.7s, 34.1s. The stiff-opener regex
in `src/core/utterance_buffer.py` strips `Sure|Okay|Got it|Great|Absolutely`
followed by `\s*` — but a comma is not whitespace, so it survives and the
utterance starts on a comma. Happened on ~4 turns.

**Fix:** extend the pattern to consume trailing punctuation,
e.g. `^(Sure|Okay|Got it|Great|Absolutely)[!,.]?\s*`, and re-capitalise the
remainder. Small, well-understood, high frequency.

---

## P1 — Ellipsis inflates the sentence count, truncating punchlines

`_SENTENCE_END` treats `.` `!` `?` `।` `…` as boundaries, so `...` counts as
**three** boundaries. With `max_sentences=3`, a joke is guillotined:

```
"సరే, ఒక జోక్ చెబుతాను."                      -> sentence 1
"ఒక రోజు ఆరెంజ్ పోలీస్ స్టేషన్ కి వెళ్ళింది..."  -> sentence 2
"ఎందుకు?"                                     -> sentence 3  (cap reached)
punchline                                      -> DROPPED
```

This explains the whole 107s–252s collapse: setup delivered, punchline cut, the
caller calls it out (*"నువ్వు దొంగ, నువ్వు joke complete చేయలేదు"*), the model
promises to retry, gets cut again, apologises, promises again. Roughly **145
seconds — 58% of the call — lost to one truncation bug.**

**Fix:** collapse runs of `.` before splitting, treat `...`/`…` as
non-terminal, and let a turn exceed the cap when it opens something that must
close (joke, list, "because…"). Consider raising `max_sentences` to 4.

---

## P2 — Banned phrases still slip through

At 9.5s: **"How can I help you today?"** — banned in `prompts/voice/system_prompt.txt`
*and* banned again in the appended block, in three languages. Said anyway, in
the second turn of the call.

Third time a prompt-level prohibition has been ignored (previously: verbatim
repetition, phone-number asking). Pattern is now clear: **negative prompt rules
are unreliable on this model.** Where a rule matters, enforce it in code —
as done for repetition in `9001b19`.

**Fix:** post-generation filter for a small banned-phrase list across hi/te/en,
substituting a natural opener.

---

## P2 — Near-duplicate apology loop escapes the repeat guard

```
209.1s  "అయ్యో, సారీ! నా voice కొంచెం తడబడింది. ఇంకోసారి స్పష్టంగా చెబుతాను."
244.4s  "అయ్యో, సారీ! నా మాటలు తడబడ్డాయి. ఇంకోసారి స్పష్టంగా చెబుతాను."
```

Semantically identical, lexically different — `_guard_repeat` compares
normalized equality, so it did not fire.

**Fix:** similarity threshold (token overlap / ratio ≈ 0.8) rather than exact
match, and track the last 2–3 replies rather than only the last one.

---

## P2 — Whole-clause code-mixing (caller complained explicitly)

At 74.5s: *"Why are you speaking half the time in English, half the response in
हिंदी"*, triggered by **"Haan, main samajh gaya. Aap live data chahte hain.
Let me check that for you."**

The prompt encourages keeping *technical words* in English inside a Hindi
sentence — natural. The model instead alternates **whole clauses**, which reads
as an unstable persona.

**Fix:** sharpen the rule — one base language per reply; English permitted for
individual technical nouns only, never for a full clause.

---

## P3 — Hindi TTS quality still reported as poor

At 207.5s: *"హిందీలో నీ voice అంతా break అయితే clumsy-గా వస్తుంది"* — Hindi
specifically, after the loudness fix resolved the general case. Suspects, in
order: the two-chunk seam (still one HTTP TTS boundary per reply), Devanagari
+ Latin mixed text confusing `bulbul:v2` preprocessing, and 22050 → 8000
resample quality. Needs a controlled A/B of Hindi-only vs mixed-script input
before changing anything.

---

## P3 — Still flying blind on latency

Fourth consecutive call logging `total_turns: 0, avg_latency_ms: 0`.
`LatencyTracker` is instantiated but never instrumented. All audio and
endpointing tuning so far has been done **without a single real turn-latency
measurement.** The instrumentation exists, unmerged, in
`_pending-merge-adr003/src/core/pipeline.py`.

**Merge it first tomorrow** — it makes everything else measurable. Note the
snapshot's version gates on `frame.finalized`, which Sarvam never sets; strip
that gate during the merge (same bug fixed in `5c74445`).

---

## Suggested order for tomorrow

1. **Merge latency instrumentation** — measure before tuning further (small).
2. **P1 ellipsis + comma fixes** — small, mechanical, recovered 58% of a call.
3. **P0 real search backend** — the actual product gap; largest piece.
4. **P2 code-level banned-phrase + fuzzy repeat guard.**
5. **P3 Hindi audio A/B**, once latency numbers exist.

Items 1–2 are under an hour combined and remove the loudest symptoms. Item 3 is
the day's real work and the thing that decides whether this feels intelligent.
