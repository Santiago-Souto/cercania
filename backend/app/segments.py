"""Transcript segments and the one rule that maps a quote to audio times (CIA-23).

A segment is {"start": float, "end": float, "text": str}: seconds from the start of
the audio, in order. Stored on report.segments: one per word when the provider returns
word timestamps (transcribe.Transcript.segment_dicts), else its segments; [] for typed reports.

Items and citations use the same rule (docs/contract.md, "Transcript segments"):
the quote's audio range is the shortest run of consecutive segments whose joined text
contains the quote (same normalization as quote verification), from the first
segment's start to the last one's end. No match, or no segments: (None, None).
Code only; the model never sees or returns times.
"""

from __future__ import annotations

from .extract import normalize


def quote_times(quote: str | None, segments: list[dict] | None) -> tuple[float | None, float | None]:
    """(start, end) of the shortest run of consecutive segments containing `quote`."""
    q = normalize(quote or "")
    texts = [normalize(str(s.get("text") or "")) for s in segments or []]
    if not q or not texts:
        return None, None
    best: tuple[int, int] | None = None
    for i in range(len(texts)):
        joined = ""
        for j in range(i, len(texts)):
            joined = f"{joined} {texts[j]}".strip()
            if f" {q} " in f" {joined} ":
                if best is None or j - i < best[1] - best[0]:
                    best = (i, j)
                break
            # Longer than the quote even without segment i: any match starts later (found from i + 1).
            if len(joined) - len(texts[i]) > len(q):
                break
    if best is None:
        return None, None
    return segments[best[0]].get("start"), segments[best[1]].get("end")
