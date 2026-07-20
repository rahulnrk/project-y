# Project Y – Product Stage & Architecture Foundation
**Date:** 2026-07-16  
**Owner:** Product Architect  
**Status:** Initial baseline (provisional – pending full context from `project y 0716.zip`)

## 1. Assumed Product Stage
**Current working assumption:** Architecture Definition / Pre-MVP → Production-grade target.

Rationale:
- Role definition explicitly calls for “production-grade”
- Daily work artifact is a large zip (likely codebase + docs)
- No live traffic, metrics, or decision logs are currently accessible outside the zip
- Therefore we treat this as the moment to lock the **system boundaries, separation of concerns, and non-negotiable constraints** before heavy implementation.

If the actual stage is different (e.g. already in private beta, or pure research), update this document immediately.

## 2. System Boundaries (Clear Separation of Concerns)

```
┌─────────────────────────────────────────────────────────────┐
│                     Telephony Edge                          │
│  (Exotel / Knowlarity / Plivo / custom SIP)                 │
└─────────────────────┬───────────────────────────────────────┘
                      │ RTP / WebSocket / SIP
┌─────────────────────▼───────────────────────────────────────┐
│                  Voice Pipeline Runtime                     │
│  (LiveKit Agents / Pipecat / custom)                        │
│  - VAD → ASR → NLU/LLM → TTS → Barge-in handling            │
└─────────────┬───────────────────────────────┬───────────────┘
              │                               │
   ┌──────────▼──────────┐         ┌──────────▼──────────┐
   │   Core Backend      │         │   Real-time State   │
   │   (API + Workers)   │         │   (Redis / NATS)    │
   └──────────┬──────────┘         └─────────────────────┘
              │
   ┌──────────▼──────────────────────────────────────────┐
   │              Data & Integration Layer               │
   │  Postgres | Object Storage | Vector DB (optional)   │
   │  External: CRM, Payment, WhatsApp, SMS              │
   └──────────┬──────────────────────────────────────────┘
              │
┌─────────────▼─────────────────────────────────────────────┐
│                    Web Dashboards                         │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────┐   │
│  │    B2C      │  │    B2B      │  │     Master      │   │
│  │ (End-user)  │  │ (Business)  │  │ (Ops / Admin)   │   │
│  └─────────────┘  └─────────────┘  └─────────────────┘   │
└───────────────────────────────────────────────────────────┘
```

## 3. Non-Negotiable India Constraints (Must drive every decision)

| Constraint              | Implication                                      | Priority |
|-------------------------|--------------------------------------------------|----------|
| End-to-end latency      | < 800–1200 ms preferred for natural feel         | P0       |
| Vernacular support      | Hindi + at least 4–5 major Indian languages      | P0       |
| Cost sensitivity        | Per-minute + infra cost must stay very low       | P0       |
| Network variability     | Graceful degradation on 3G / flaky mobile data   | P0       |
| Reliability             | 99.5%+ call success, no single point of failure  | P0       |
| Maintainability         | Small team must be able to operate & iterate     | P1       |

## 4. Recommended Starting Tech Choices (Simple & Proven)

### Voice Pipeline
- **Orchestration**: LiveKit Agents (or Pipecat) – proven real-time, good Python/TS support
- **ASR**: Primary – Sarvam / Azure Speech (Indic) or Whisper large-v3 + fine-tune; fallback Google
- **LLM**: Grok (xAI) or GPT-4o-mini for cost; keep option for local/quantized models later
- **TTS**: Azure Neural / ElevenLabs multilingual or IndicTTS; cache common phrases aggressively
- **Telephony**: Start with Exotel or Knowlarity (India-local, lower latency & cost than pure Twilio)

**Trade-off note**: LiveKit gives us production-grade WebRTC + SIP bridge quickly. Custom WebSocket pipeline would be more control but higher maintenance – rejected for now.

### Backend
- Language: TypeScript (NestJS or Hono) or Python (FastAPI) – prefer one language across voice + backend if possible
- DB: PostgreSQL (Supabase or managed RDS in ap-south-1)
- Cache / Real-time: Redis
- Queue: BullMQ or NATS
- Auth: Clerk or Supabase Auth (fast to production)

### Dashboards
- Framework: Next.js 15 (App Router) + Tailwind + shadcn/ui
- Hosting: Vercel or Cloudflare Pages (edge close to India users)
- Separate apps or monorepo with clear route groups for B2C / B2B / Master

## 5. Immediate Next Actions (Product Architect ownership)

1. **Unblock context** – Get key files out of the 215 MB zip (context.md, decisions.md, current stack, any existing diagrams).
2. Lock the telephony provider shortlist and run latency tests from major Indian cities.
3. Define the minimal viable voice turn (happy path + barge-in + fallback).
4. Create `decisions.md` log and start recording every architecture choice with date + rationale.
5. Sketch the data model for Call Session, User, Business, Conversation Turn.

---

**This document is the living foundation.**  
All subsequent architecture work must reference or update it.

Next update expected once the zip contents (or extracted core files) are available.
