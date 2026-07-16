# AI Phone Assistant Platform - Technical Specification

**Version**: 1.0 (Phase 1 - B2C MVP)  
**Date**: July 14, 2026  
**Status**: In Active Development  
**Owner**: Solo Founder (NRK)

---

## 1. Product Vision

**Name**: AI Phone Assistant (working name: *Sahaay*)

**Mission**: Build a natural, safe, memory-enabled voice AI that feels like talking to a real, caring person — accessible via a simple phone call in India.

**Core Differentiators**:
- Extremely natural conversation (pauses, warmth, short sentences)
- Persistent memory across calls (per phone number)
- Strong safety with soft, empathetic redirects (safe for all ages)
- One infrastructure for both **B2C personal use** and future **B2B customer engagement**
- Privacy-first with user control ("Forget me")

**Target Users (Phase 1)**: Hindi, Telugu, and English speaking users in India who prefer phone over apps.

---

## 2. High-Level Architecture

```
Exotel Voicebot (WebSocket)
        ↓
FastAPI Server (/exotel-stream)
        ↓
Per-Call Pipecat Pipeline
├── Transport (Exotel)
├── Sarvam STT (codemix mode)
├── SafetyGuardrailProcessor (parallel, non-blocking)
├── LLMContextAggregator
├── LLM (Hybrid routing planned)
├── Sarvam TTS (user-selected voice)
└── Post-call hooks (memory update)
        ↓
Memory Layer (Redis)
        ↓
B2C Portal + Master Command Center (Future)
```

**Key Principles**:
- Async-first everywhere
- Safety runs in parallel (zero latency impact on happy path)
- Memory loaded at call start, updated after call ends
- Clean separation between B2C and future B2B contexts

---

## 3. Core Components

### 3.1 Configuration (`src/config.py`)

- **Languages**: `hi-IN`, `te-IN`, `en-IN` (full support from Day 1)
- **Voices**: 7 preset voices (4 female, 3 male) from Sarvam
- **Safety Mode**: `soft_redirect` + `safe_for_all_ages = True`
- **Product Limits**: Free minutes per day, max recent facts, etc.

### 3.2 Data Model (`src/models/caller_profile.py`)

**CallerProfile** (stored per normalized phone number):

```python
phone_number, name, age, gender, language, voice_id, voice_gender_pref
first_call_at, last_call_at, total_calls, total_minutes
rolling_summary, recent_facts (list)
is_b2b_customer, business_id, campaign_id (future)
memory_enabled, consent_given_at
```

**Key Method**: `to_context_blob()` — injects short memory into LLM system prompt.

### 3.3 Memory Layer (`src/memory/memory_store.py`)

- Redis-backed (works with Upstash)
- One key per caller: `caller:{digits}:profile`
- Functions:
  - `start_call()` → bump counters + return profile
  - `append_call_summary()` → update rolling summary + facts (off critical path)
  - `delete_user_data()` → privacy "Forget me"
  - `update_voice_preference()`

### 3.4 Safety Guardrails (`src/guardrails/`)

**Design**: Parallel + non-blocking.

**Detection Categories**:
- `crisis` / self-harm → Warm Tele MANAS redirect
- `sexual` / romantic → Soft empathetic redirect
- `harm` to people/animals → Clear but warm redirect
- `abuse` / harassment → Calm boundary setting

**Philosophy**: Soft redirects preferred over hard blocks. Safe for all ages by design.

### 3.5 Onboarding Flow (`src/core/onboarding.py`)

**First-call sequence** (5–6 turns max):

1. Friendly intro (Hindi)
2. Ask name → Smart extraction
3. Ask age (optional)
4. Ask gender
5. Voice preference selection (from preset list)
6. Language preference (Hindi / Telugu / English)
7. Onboarding complete → Normal conversation begins

Profile is saved after every turn.

### 3.6 Voice Pipeline (`src/core/pipeline.py`)

**Full real-time pipeline**:
- `FastAPIWebsocketTransport` + Exotel serializer
- `SileroVADAnalyzer` for natural barge-in
- `SarvamSTTService` (codemix mode)
- `SafetyGuardrailProcessor`
- `LLMContextAggregatorPair`
- `OpenAILLMService` (or Sarvam LLM)
- `SarvamHttpTTSService` (user’s chosen voice)

---

## 4. Safety Design (Detailed)

**Goal**: Maximum safety with minimum friction for normal users.

**Layers**:
1. **Pre-LLM Rules** (fast keyword patterns)
2. **Parallel Classifier** (runs alongside main flow)
3. **System Prompt Steering**
4. **Warm, empathetic redirect language**

**Never**:
- Engage with sexual/romantic content (regardless of stated age)
- Assist with harm to self, others, or animals
- Escalate abuse

**Always**:
- Redirect warmly
- Offer alternative topics
- Provide real helplines for crisis

---

## 5. Cost & Efficiency Strategy

**Target**: Keep per-minute cost low while maintaining quality.

**Planned Techniques**:
- Smart LLM routing (fast/cheap model by default)
- Parallel safety (no extra latency)
- Efficient Redis usage (single key per user)
- Caching of common responses (future)
- Token usage tracking per call

**Monitoring** (to be added in Option C):
- Per-call cost estimation
- Voice-to-voice latency measurement
- Safety trigger rate

---

## 6. Technical Roadmap

### Phase 1 (Current) — B2C MVP
- Working multi-user calls
- First-call onboarding with voice selection
- Persistent memory + rolling summary
- Soft safety guardrails
- Basic local testing possible

### Phase 2 (Next)
- Cost tracking + latency logging
- Basic B2C usage portal
- Improved onboarding with real LLM extraction
- Better error handling & graceful degradation

### Phase 3
- B2B layer (knowledge base upload, campaign context)
- B2B company dashboard
- Master Command Center
- Outbound calling support

### Phase 4
- Payments (Razorpay)
- Advanced analytics
- Marketplace (voice packs, skills)
- Human agent fallback

---

## 7. Key Files (Current State)

```
src/
├── config.py
├── models/caller_profile.py
├── memory/memory_store.py
├── guardrails/
│   ├── rules.py
│   └── processor.py
├── core/
│   ├── onboarding.py
│   └── pipeline.py
└── api/server.py
```

**Entry Point**: `python -m src.api.server`

---

## 8. Open Questions / TODOs

- Exact field names in real Exotel `start` event payload (verify on first test call)
- Final LLM choice (Sarvam vs OpenAI vs hybrid)
- Exact voice IDs available in current Sarvam TTS
- DPDP Act compliance review (legal)
- Production deployment platform (Railway vs Render vs Fly.io)

---

**Document Status**: Living document. Will be updated as development progresses.

---

*Built with care for natural, safe, and accessible voice AI in India.*