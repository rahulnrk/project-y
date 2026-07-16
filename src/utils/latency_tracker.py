"""
latency_tracker.py - Voice-to-voice latency and cost tracking (Option C)
"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CallMetrics:
    call_start: float = field(default_factory=time.time)
    user_stopped_speaking: Optional[float] = None
    agent_started_speaking: Optional[float] = None
    total_turns: int = 0
    estimated_cost_inr: float = 0.0
    latency_samples: list = field(default_factory=list)


class LatencyTracker:
    def __init__(self):
        self.metrics = CallMetrics()

    def mark_user_finished(self):
        self.metrics.user_stopped_speaking = time.time()

    def mark_agent_started(self):
        self.metrics.agent_started_speaking = time.time()
        if self.metrics.user_stopped_speaking:
            latency = (self.metrics.agent_started_speaking - self.metrics.user_stopped_speaking) * 1000
            self.metrics.latency_samples.append(latency)
            print(f"[LATENCY] Turn latency: {latency:.0f}ms")

    def add_cost(self, estimated_inr: float):
        self.metrics.estimated_cost_inr += estimated_inr

    def get_summary(self) -> dict:
        avg_latency = (
            sum(self.metrics.latency_samples) / len(self.metrics.latency_samples)
            if self.metrics.latency_samples else 0
        )
        return {
            "total_turns": self.metrics.total_turns,
            "avg_latency_ms": round(avg_latency, 1),
            "estimated_cost_inr": round(self.metrics.estimated_cost_inr, 4),
            "call_duration_sec": round(time.time() - self.metrics.call_start, 1)
        }

    def reset(self):
        """Kept for API compatibility -- prefer just creating a new
        LatencyTracker() per call instead of resetting a shared one."""
        self.metrics = CallMetrics()


# NOTE: no module-level shared instance here on purpose. With multiple
# simultaneous callers, one global tracker would mix samples across calls and
# let one call's reset() clobber another call's in-progress metrics.
# Create LatencyTracker() fresh inside build_b2c_pipeline() per call instead.