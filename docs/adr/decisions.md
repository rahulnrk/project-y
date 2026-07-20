# Project Y – Architecture Decision Log

Format:  
**ADR-XXX** | Date | Title  
Status: Proposed / Accepted / Deprecated  
Context → Decision → Consequences → Trade-offs

---

## ADR-001 | 2026-07-16 | Product Stage Baseline
**Status:** Accepted (provisional)

**Context**  
Only artifact available is a 215 MB zip. No prior decisions.md or context.md readable. Role definition targets production-grade system for India.

**Decision**  
Treat current stage as Architecture Definition / Pre-MVP with production-grade target. All work prioritizes clear separation of concerns, India constraints, and simple proven tech.

**Consequences**  
- We can start locking boundaries and tech choices immediately.
- Full context from zip is still required before implementation-heavy decisions.

**Trade-offs**  
Speed of starting vs risk of mis-aligned assumptions. Mitigated by marking everything provisional and requiring update once zip is accessible.

---

## ADR-002 | 2026-07-16 | High-level System Boundaries
**Status:** Proposed

**Context**  
Need clear separation between telephony edge, real-time voice pipeline, core backend, and the three dashboards.

**Decision**  
Adopt the layered architecture shown in `00-product-stage-and-architecture-foundation.md`:
- Telephony Edge
- Voice Pipeline Runtime (LiveKit / Pipecat style)
- Core Backend + Real-time State
- Data & Integration Layer
- Web Dashboards (B2C / B2B / Master as separate concerns)

**Consequences**  
Voice pipeline stays isolated and can be scaled/replaced independently. Dashboards never talk directly to telephony or ASR/TTS.

**Trade-offs**  
Slightly more moving parts vs a monolithic “everything in one process” approach. Chosen for maintainability and future multi-tenant needs.

---

## ADR-003 | 2026-07-16 | Voice Improvement Sequence (Barge-in + Latency)
**Status:** Accepted  
**Source:** Founder confirmation of Scrum synthesis (Option 2) + Voice Pipeline / Safety / Product Architect inputs

**Context**  
Barge-in is currently non-functional (VAD not wired). LatencyTracker exists but is never instrumented. Safety TTS can race with main path. Target <800–1200 ms voice-to-voice.

**Decision**  
Adopt balanced sequence for today:
1. Wire SileroVADAnalyzer + basic interruptions + LatencyTracker instrumentation.
2. Add safety priority frame handling so crisis/Tele MANAS redirects cannot be cancelled by barge-in.
3. Expand vernacular (Hindi/Telugu/Hinglish) patterns in rules.py in the same window.
4. Defer full streaming TTS coordination (Option B) until baseline numbers exist.

**Consequences**  
- Usable barge-in + real latency numbers available today.
- Safety non-negotiables protected.
- Clean data for Master dashboard and Testing agent.

**Trade-offs**  
Slightly more coordination required between Voice and Safety vs pure sequential work. Chosen for highest velocity with low risk.

---

## ADR-004 | 2026-07-16 | Measurement & Logging Contracts
**Status:** Accepted  
**Source:** Founder confirmation + Product Architect guidance + Safety requirements

**Context**  
No measured latency numbers exist. Master dashboard and Testing need consistent events. Safety needs auditable triggers without PII.

**Decision**  
1. **Latency / Barge-in events** (Voice Pipeline must emit):
   - user_finished (VAD end-of-speech or final STT)
   - agent_started (first TTS audio frame)
   - barge_in_detected / barge_in_successful
   - component timings (STT, LLM TTFT, TTS first-byte)

2. **Safety Event schema** (minimal, privacy-first):
   - category, language, timestamp, call_id_hash, redacted_trigger, action_taken, helpline_offered

3. Master dashboard will consume only aggregated / high-level versions of the above. No full transcripts or raw PII.

**Consequences**  
All agents can implement against the same contract. Master can show real numbers immediately.

**Trade-offs**  
Slightly more logging code now vs later rework. Chosen to prevent future pain.

---

## ADR-005 | 2026-07-16 | Master Dashboard MVP Scope
**Status:** Accepted  
**Source:** Founder confirmation of Product Architect proposal

**Context**  
Founder needs a control plane view. Must stay thin, privacy-aware, and focused on system health rather than user content.

**Decision**  
Master dashboard MVP views:
- System Health (active calls, success rate, p50/p95 latency, service health)
- Usage & Cost (minutes, estimated cost, language/voice mix)
- Safety Overview (trigger rates by category, Tele MANAS redirects, high-level trends)
- Reliability & Alerts
- Tenant Snapshot (aggregate counts only)

Implementation notes:
- 5-minute aggregates preferred initially
- Single founder account auth for v1
- No full transcripts, no raw memory facts, no individual tenant configuration

**Consequences**  
Clear boundary for Data & Dashboard agent. Privacy and cost stay controlled.

**Trade-offs**  
Less real-time depth vs full analytics platform. Chosen for speed and low operational cost at this stage.

---

*(More ADRs will be added as decisions are made)*
