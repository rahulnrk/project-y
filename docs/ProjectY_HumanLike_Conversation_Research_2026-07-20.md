# Project Y – Research Notes: Human-like Conversation Analysis  
**Benchmarking ChatGPT Advanced Voice / GPT-Live**  
**Date:** 20 July 2026  
**Author:** Testing & Iteration Agent  
**Status:** End-to-end synthesis of thread discussion + external research  
**Related ADRs:** ADR-003 (Voice Improvement Sequence – VAD + interruptions), ADR-004 (Measurement & Logging)

---

## 1. Original Product Feedback (Thread Start)

User tested the product:
- Functional overall.
- AI responses are wrong / off-topic / inaccurate in places.
- Does not feel like a conversation.
- Feels robotic.
- Not human-like in answering style.

Key pain points identified in discussion:
- Lack of natural pauses and conversational flow.
- Repetitive phrasing / limited lexical variety.
- Weak interruption / active listening handling.
- Language and context handling need to match Indian vernacular use (Telugu example shared).

---

## 2. Thread Discussion Summary (Chronological)

### Phase 1 – Brainstorm: How ChatGPT Voice Feels Human
- Focus areas: good pauses, different terms (lexical variety), avoiding repetition.
- Research findings (from OpenAI docs, system cards, independent measurements, and user reports):
  - **Native multimodal audio model** (GPT-4o lineage → GPT-Live): processes raw audio in and out. Captures prosody, emotion, tone, breathing, non-verbal cues, speaker differentiation.
  - **Full-duplex continuous architecture** (GPT-Live, launched ~July 2026): listens and speaks simultaneously. Makes interaction decisions many times per second (speak / continue listening / pause / interrupt / invoke tool).
  - Extremely low latency (~320 ms voice-to-voice in earlier Advanced Voice; full-duplex further improves natural turn-taking).
  - Backchanneling (“mhmm”, “yeah”) while user is still speaking.
  - Handles long thinking pauses without cutting the user off.
  - Emotional / tonal awareness and natural breathing/pauses in output.

### Phase 2 – Concrete Example Shared by User
Screenshots of a multi-turn ChatGPT conversation (text + voice UI) about the “Cockroach Janta Party” (CJP) / “Chalo Sansad” protests in Delhi (youth unemployment, exam paper leaks, etc.).

Observed strengths:
- Seamless language switching: English → “Telugu-lo cheppuu” → full natural Telugu responses with no announcement.
- Progressive disclosure of information (high-level summary → origin of name → key people → police response → timeline).
- Discourse markers: “Hang on. Checking the latest.”, “Hm.”, “సరే, చూస్తున్నా.”, “అవును తెలుగులో చెబుతాను.”
- Lexical variety – each turn adds new details with different wording (no copy-paste repetition).
- Source grounding (TOI, India Today, etc.).
- Multi-turn coherence and entity tracking (leaders, dates, demands).

User clarification:
> “Response of this sizes are actually fine but if the user interrupts and asks a question or anything should actively listen as well to respond.”

### Phase 3 – Focus Shift to Active Listening / Interruptions
- Long responses are acceptable.
- Critical requirement: when user barges in mid-response, the system must detect, stop cleanly, listen to the new input, and pivot to answer the new question/direction.
- This is a primary driver of “feels like a conversation” vs “robotic monologue”.

---

## 3. Detailed Research: How ChatGPT Mimics Human-Kind of Talk

### 3.1 Language Switching & Code-Mixing
- Models show high query-language fidelity (especially GPT-family: 95%+ when switching back to English after foreign-language context; near-perfect when switching into a non-English language).
- Trained on massive code-switched data (social media, bilingual forums, subtitles). Handles mixed-script and intra-utterance switches (e.g., English technical terms inside Telugu) with good pragmatic continuity.
- In voice mode: native audio understanding detects language from speech signal; user can set preferred “Main Language” in settings. Live speech translation mode also exists (continues translating until told to stop).
- No forced announcement of language change – mirrors natural human code-switching.

**Implication for Project Y:** Sarvam STT + LLM prompt must support robust language detection and immediate matching (including Hinglish / Telugu-English mixes common in India). Explicit system-prompt rules for “match user’s language and code-mixing style” are effective.

### 3.2 Context Awareness
- Maintains continuous dialogue context (reported 30+ minutes in Advanced Voice).
- Tracks not only text but vocal cues (tone, emphasis, hesitation patterns).
- Long-term memory via “Dreaming” system (background process that curates and refreshes relevant context across chats, time-aware – understands when events are past/present/future).
- Progressive, non-repetitive responses: uses prior turns to expand rather than restate.
- In the CJP example: remembered the topic, entities, and previous answers while adding new layers.

**Implication for Project Y:** Need short-term conversation memory (recent turns + key entities/facts) + optional longer-term Redis-backed memory with consent. Prompt must instruct “build on previous context, avoid repeating the same phrases.”

### 3.3 Extending Search Parameters / Tool Use for Current Events
- High web-search trigger rate for temporal/news queries (~78% observed in analyses).
- GPT-Live architecture: the continuous voice model can **delegate** heavy search or reasoning to a frontier model (e.g., GPT-5.5) in the background while continuing to interact with the user (fillers, partial answers, or simply waiting naturally).
- Query reformulation is context-aware: conversation history expands the original query (e.g., “CJP” → “Cockroach Janta Party origin + key leaders + recent Delhi march + police response”).
- Results are grounded with sources and sometimes visual cards (weather, stocks, sports).
- “Hang on. Checking the latest.” is a natural discourse marker while the tool runs.

**Implication for Project Y:** Current-events / knowledge queries require a search or knowledge tool. The voice pipeline should support non-blocking tool calls (continue speaking or use natural pauses/fillers while results arrive). Query expansion from conversation history is essential to avoid shallow or off-topic answers.

### 3.4 Full Communication Pipeline – How Everything Connects
ChatGPT’s human-like feel emerges from the tight integration of:

1. **Audio Input** → Native multimodal understanding (not pure ASR cascade).
2. **Continuous Decision Loop** (full-duplex) → Micro-decisions many times/second on turn dynamics, backchannels, tool invocation.
3. **Context + Memory** → Short-term dialogue state + long-term “dreaming”.
4. **Reasoning / Tools** → Delegation for search/deeper work without freezing the conversation.
5. **Audio Output** → Prosody-aware generation with natural pauses, breathing, emotional tone, variable pacing.
6. **Safety / Guardrails** → Parallel monitoring that can interrupt or steer mid-response.

This is fundamentally different from a classic cascaded pipeline (STT → LLM → TTS) that waits for a clean “end of user turn”.

**Key technical enablers of naturalness:**
- Full-duplex (listen while speaking).
- Continuous rather than discrete turns.
- Native audio (prosody & non-verbals preserved).
- Low and consistent latency.
- Explicit support for backchannels and graceful interruption.

---

## 4. Mapping to Project Y Stack (Pipecat + Sarvam + Exotel + FastAPI + Redis)

| ChatGPT Capability                  | Current Project Y Reality                          | Recommended Path                                      | Priority |
|-------------------------------------|----------------------------------------------------|-------------------------------------------------------|----------|
| Full-duplex / active listening     | Cascaded; barge-in work in progress (ADR-003)     | Complete SileroVAD + interruption + clean TTS stop   | **P0**  |
| Language / code-mixing             | Sarvam supports Indic; prompt rules needed         | Strong language-matching + spoken-style system prompt| **P0**  |
| Lexical variety / anti-repetition  | Not yet systematically addressed                   | Prompt instructions + recent-phrase tracking          | **P0**  |
| Progressive / non-monologue replies| Long responses currently accepted by user          | Spoken-style prompt (short sentences, invite continue)| High    |
| Context awareness                  | Basic history; Redis memory planned                | Robust short-term state + entity tracking             | High    |
| Current-events search              | Not yet confirmed                                  | Non-blocking tool call + query expansion from history | High    |
| Natural pauses / backchannels      | Limited                                            | TTS prosody controls + explicit backchannel logic     | Medium  |
| Measurement                        | LatencyTracker planned (ADR-004)                   | Instrument interruption latency + subjective naturalness scores | High |

---

## 5. Prioritized Recommendations (from this Research)

**Immediate (this week)**
1. Finalize and test barge-in / active listening path (detect → clean stop → process new input → pivot). Define success criteria:
   - Detection latency
   - Stop quality (no harsh mid-word cuts)
   - Correctness of response to the interrupting utterance
   - Subjective “felt natural” rating
2. Overhaul system prompt for:
   - Spoken Telugu / Hinglish / English style
   - Explicit language matching and code-mixing comfort
   - Anti-repetition / lexical variety
   - Progressive disclosure + natural discourse markers
3. Instrument interruption metrics (extend ADR-004 contracts).

**Short-term**
4. Add non-blocking search/tool capability for current events with conversation-aware query expansion.
5. Strengthen short-term conversation memory (key entities, previous answers, user language preference).

**Measurement**
- Create a small test suite of Telugu / mixed-language multi-turn scenarios (including the CJP-style current-events flow).
- Rate each on: language fidelity, context coherence, interruption handling, lexical variety, factual grounding, overall conversational feel.

---

## 6. Open Questions / Next Research Threads

- Exact current barge-in behavior and failure modes observed in user testing (does it ignore, cut badly, resume old response, or fail to answer the new question?).
- Sarvam TTS prosody / pause / breathing control capabilities.
- Preferred maximum spoken response length before inviting continuation (even if user said longer is fine).
- Whether a lightweight “rephraser” step or higher sampling temperature is needed for variety.
- How aggressively to expand search queries from conversation history vs staying faithful to the latest user utterance.

---

## 7. Sources & References (Key External Research)

- OpenAI: Introducing GPT-Live (full-duplex architecture, continuous decisions, delegation for search).
- OpenAI GPT-Live System Card (2026-07-08).
- Independent latency & interruption measurements (Agora, Roark, etc.).
- Multilingual / code-switching evaluations (ACL 2026 MultiChallenge extension, ChatGPT-4o vs Gemini comparisons).
- ChatGPT memory “Dreaming” system and time-aware context.
- Analyses of web-search trigger rates and query reformulation in conversational settings.
- User reports and screenshots from the live thread (CJP Telugu multi-turn example).

---

**This document is the living research baseline for human-like conversation work in Project Y.**  
All subsequent prompt, VAD, interruption, and tool-use changes should reference or update it.

Next update expected after first interruption test results or system-prompt iteration.  
Prepared for sharing with Voice Pipeline, Product Architect, and Scrum Master agents.
