# Project Y - Shared Context (Single Source of Truth)

## Product Vision
AI voice phone assistant platform for India with vernacular + Hinglish support.
Phone-first experience + web dashboards (B2C users, B2B customers, Master dashboard for founder).

## Current Tech Stack
- Voice: Pipecat + Sarvam + Exotel
- Backend: FastAPI + Redis
- Web: Dashboards for B2C, B2B, and Master
- Safety: Pre-LLM classifiers + helplines (parallel, non-blocking)
- Memory: Redis (minimal + consent-based)

## Latest Decisions Log
**Date:** 16 July 2026

### Confirmed Decisions (today)
- **ADR-003**: Voice improvement sequence = Wire VAD + interruptions + LatencyTracker + safety priority frames + expand vernacular safety patterns (Option 2 Balanced). Defer full streaming TTS until baseline numbers exist.
- **ADR-004**: Measurement & logging contracts locked (latency/barge-in events + minimal Safety Event schema). Privacy-first.
- **ADR-005**: Master dashboard MVP = 5 thin views (System Health, Usage & Cost, Safety Overview, Reliability & Alerts, Tenant Snapshot). Single founder auth. 5-min aggregates. No transcripts/PII.

Full details in `decisions.md`.

## Current Agent Status
- Product Architect: Guidance delivered. Awaiting implementation feedback.
- Voice Pipeline: Ready to implement ADR-003 (VAD + tracker + safety priority).
- Safety & Guardrails: Ready to expand rules.py + review safety priority frames.
- Data & Dashboard: Next up – implement Master MVP against ADR-004/005 contracts.
- Testing & Iteration: Waiting for measurable baseline.
- Scrum / Context Agent: Context updated. Coordinating.

## Open Questions / Blockers
- Actual baseline p50/p95 latency numbers (will come after instrumentation).
- Confirmation of Sarvam TTS true streaming support (for later Option B).
- Founder priority ranking among the 5 Master views for absolute first usable version.
- Preferred metrics retention period (7 / 30 / 90 days).
- Any additional “must see every morning” metric for Master.
