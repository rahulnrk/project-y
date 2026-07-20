"""
web_search.py - Live current-events answers via Google News RSS (no API key).

NewsInjectProcessor sits before the LLM. When a user turn looks like a
current-events question (news / weather / prices / scores / "aaj ki khabar"),
it: (1) speaks a short language-appropriate filler immediately so the line is
never silent, (2) fetches headlines with a hard timeout, (3) appends a system
message with the results so the LLM answers from real data, then forwards the
transcript. On any failure the turn proceeds without results and the prompt's
honesty rule applies (say you can't check, never invent).
"""

import asyncio
import re
import urllib.parse
import xml.etree.ElementTree as ET

import aiohttp
from loguru import logger

from pipecat.frames.frames import Frame, TranscriptionFrame, TTSSpeakFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

FETCH_TIMEOUT_S = 3.0
MAX_HEADLINES = 4

# Current-events intent. Deliberately conservative: false positive = wasted
# fetch + odd filler; false negative = the honesty rule answers instead.
_INTENT = re.compile(
    r"news|headline|samachar|khabar|khabre|ख़बर|खबर|समाचार|"
    r"వార్తలు|న్యూస్|"
    r"weather|mausam|barish|मौसम|बारिश|వాతావరణం|వర్షం|"
    r"\blatest\b|\btoday'?s\b|aaj (ki|ka|ke)|తాజా|"
    r"score|match (score|result)|"
    r"price of|rate of|petrol|diesel|gold rate|share market|sensex|nifty",
    re.IGNORECASE,
)

_FILLERS = {
    "hi-IN": "Ek second, dekh raha hoon...",
    "te-IN": "ఒక్క క్షణం, చూస్తున్నా...",
    "en-IN": "One sec, let me check...",
}

_STOP_WORDS = re.compile(
    r"\b(what|is|are|the|a|an|tell|me|about|please|today|now|latest|"
    r"kya|hai|hain|batao|bataiye|aaj|ki|ka|ke|mein|"
    r"చెప్పు|చెప్పండి|ఏమిటి|గురించి|ఈరోజు)\b",
    re.IGNORECASE,
)


def looks_like_current_events(text: str) -> bool:
    return bool(text and _INTENT.search(text))


def _build_query(text: str) -> str:
    """Reduce the utterance to search terms; empty -> India top stories."""
    q = _STOP_WORDS.sub(" ", text)
    q = re.sub(r"[^\w\sऀ-ॿఀ-౿]", " ", q)
    q = " ".join(q.split())
    return q or "India top stories"


async def fetch_headlines(query: str, session: aiohttp.ClientSession) -> list[str]:
    """Top headlines for query from Google News RSS. Empty list on any failure."""
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=en-IN&gl=IN&ceid=IN:en"
    )
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=FETCH_TIMEOUT_S)
        ) as resp:
            if resp.status != 200:
                return []
            xml = await resp.text()
        root = ET.fromstring(xml)
        out = []
        for item in root.findall(".//item")[:MAX_HEADLINES]:
            title = (item.findtext("title") or "").strip()
            date = (item.findtext("pubDate") or "").strip()[:16]
            if title:
                out.append(f"{title} ({date})" if date else title)
        return out
    except Exception as e:
        logger.warning(f"news fetch failed for {query!r}: {e}")
        return []


class NewsInjectProcessor(FrameProcessor):
    """Detect current-events questions, fetch real headlines, inject into context."""

    def __init__(self, context, profile, aiohttp_session):
        super().__init__()
        self._context = context
        self._profile = profile
        self._session = aiohttp_session

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and looks_like_current_events(frame.text):
            # 1. Mask the fetch latency with an immediate spoken filler.
            filler = _FILLERS.get(self._profile.language or "hi-IN", _FILLERS["hi-IN"])
            await self.push_frame(TTSSpeakFrame(text=filler), FrameDirection.DOWNSTREAM)

            # 2. Fetch (hard-capped by FETCH_TIMEOUT_S).
            query = _build_query(frame.text)
            headlines = await fetch_headlines(query, self._session)
            logger.info(f"news inject: q={query!r} -> {len(headlines)} headlines")

            # 3. Give the LLM real data for this turn.
            if headlines:
                bullets = "\n".join(f"- {h}" for h in headlines)
                self._context.add_message(
                    {
                        "role": "system",
                        "content": (
                            "LIVE SEARCH RESULTS (fetched seconds ago, real):\n"
                            f"{bullets}\n"
                            "Answer the caller's question from these. Pick the 1-2 "
                            "most relevant items and say them conversationally in the "
                            "caller's language -- do not read every headline, do not "
                            "read dates or source names unless asked."
                        ),
                    }
                )

        await self.push_frame(frame, direction)
