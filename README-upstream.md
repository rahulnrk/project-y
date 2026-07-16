# AI Phone Assistant Platform (B2C + B2B Ready)

**Current Phase**: B2C MVP foundation (July 2026)  
**Strategy**: Build B2C first for real testing, with clean multi-tenant architecture ready for B2B.

## Key Decisions

- **B2C First**: Real user testing before adding B2B complexity
- **Languages from Day 1**: Hindi (hi-IN), Telugu (te-IN), English (en-IN)
- **Voice Selection**: During B2C onboarding (user chooses from preset voices)
- **Safety**: Soft empathetic redirects (safe for all ages). No hard blocks where possible.
- **Memory**: Persistent per-phone-number profile + rolling summary + recent facts
- **Privacy**: User can delete all data anytime

## Architecture Goal

One shared high-quality voice infrastructure serving:
- **B2C**: Personal AI companions
- **B2B**: Business customer engagement (reviews, sales, service)

## Current Progress

- [x] Centralized config with languages + voices
- [x] CallerProfile model (B2C + B2B fields)
- [x] MemoryStore (Redis)
- [x] Basic Exotel WebSocket server skeleton

## Next Immediate Work

1. Full Pipecat pipeline (STT → Guardrails → LLM → TTS)
2. First-call onboarding flow
3. Soft safety redirect system
4. Basic B2C usage portal

## Safety Approach

- Warm, empathetic redirects for sensitive topics
- Immediate helpline redirect for self-harm/crisis
- Never engage with sexual/romantic content (regardless of stated age)
- Careful with abuse, harassment, and harmful requests

## Cost Philosophy

Keep API + infra costs low through:
- Smart model routing (fast models by default)
- Efficient memory usage
- Parallel (non-blocking) guardrails
- Caching where possible

---

Built as a solo founder project. Clean, safe, natural voice AI for India.