from pathlib import Path

import pytest

from auditpace.read.reader import READ_PROMPT, ReaderError, transcribe


class Stub:
    def __init__(self, content, finish="stop"):
        self.content, self.finish, self.calls = content, finish, []

    def chat_full(self, messages, *, images=None, temperature=None, max_tokens=None, extra=None, **kw):
        self.calls.append((messages, images, temperature, max_tokens, extra))
        return self.content, self.finish


def test_transcribe_returns_raw_content_and_passes_params(tmp_path):
    img = tmp_path / "p.jpg"
    c = Stub("Line one\nLine two\n")
    assert transcribe(c, img, max_tokens=512) == "Line one\nLine two\n"
    (messages, images, temperature, max_tokens, extra), = c.calls
    assert messages == [{"role": "user", "content": READ_PROMPT}]
    assert images == [img] and temperature == 0.0 and max_tokens == 512
    assert extra is None


def test_transcribe_passes_repetition_penalty_as_extra(tmp_path):
    img = tmp_path / "p.jpg"
    c = Stub("Line one\n")
    transcribe(c, img, max_tokens=512, repetition_penalty=1.1)
    (_, _, _, _, extra), = c.calls
    assert extra == {"repetition_penalty": 1.1}


def test_length_finish_raises():
    with pytest.raises(ReaderError, match="length"):
        transcribe(Stub("x" * 10, "length"), Path("p.jpg"), max_tokens=10)


def test_empty_raises():
    with pytest.raises(ReaderError, match="empty"):
        transcribe(Stub("  \n"), Path("p.jpg"), max_tokens=10)


def test_prompt_wording():
    assert "Transcribe every word" in READ_PROMPT and "line breaks" in READ_PROMPT
