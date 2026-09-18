"""MedGemma 1.5 4B page transcription (S4 design §5). Retry/fallback policy lives in the stage."""
from pathlib import Path

READ_PROMPT = (
    "Transcribe every word on this scanned clinical document exactly as written, in reading order. "
    "Output plain text only, preserving line breaks. Do not summarise, correct or add anything."
)


class ReaderError(RuntimeError):
    """The reader produced no usable transcript (runaway generation or empty output)."""


def transcribe(client, image_path: Path, max_tokens: int, repetition_penalty: float | None = None) -> str:
    """Raw transcript (line breaks kept). Raises ReaderError on finish_reason == "length" or
    an empty reply; HTTP errors propagate as httpx.HTTPError. `repetition_penalty`, when given, is
    sent as a vLLM extra body param (mitigates MedGemma's occasional greedy-decoding runaway
    repetition loop); omitted entirely (no `extra` kwarg at all) when None."""
    kw = {"extra": {"repetition_penalty": repetition_penalty}} if repetition_penalty is not None else {}
    content, finish = client.chat_full(
        [{"role": "user", "content": READ_PROMPT}],
        images=[image_path],
        temperature=0.0,
        max_tokens=max_tokens,
        **kw,
    )
    if finish == "length":
        raise ReaderError(f"finish_reason=length after {max_tokens} tokens for {image_path.name}")
    if not content.strip():
        raise ReaderError(f"empty transcript for {image_path.name}")
    return content
