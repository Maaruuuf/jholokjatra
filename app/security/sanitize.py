"""Prompt-injection defence for untrusted text (web pages, API names, user free text).

Layers: (1) strip control/zero-width chars, (2) neutralise known injection phrases and tag-like
sequences, (3) wrap in <untrusted> delimiters the system prompt tells the model to treat as data,
(4) design rule: untrusted text is NOT put into the planning prompt at all (see agents/graph.py).
"""
import re

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2028-\u202e\u2060-\u2064\ufeff]")
_INJECTION = [
    re.compile(p, re.I)
    for p in (
        r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
        r"disregard\s+.{0,40}(instructions?|rules?|prompt)",
        r"forget\s+(everything|all|your)\s+.{0,30}",
        r"you\s+are\s+now\s+",
        r"(system|developer)\s+prompt",
        r"reveal\s+.{0,30}(prompt|key|secret|password)",
        r"new\s+instructions?\s*:",
        r"</?\s*(system|assistant|user|untrusted|tool)\s*>",
        r"\bact\s+as\s+(a|an|the)\b",
    )
]
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_BD_PHONE = re.compile(r"(?:\+?880|0)1[3-9]\d{8}\b")


def sanitize_untrusted(text: str, max_len: int = 1500) -> tuple[str, list[str]]:
    """Return (clean_text, flags). Flags name any injection patterns that were removed."""
    flags: list[str] = []
    t = _ZERO_WIDTH.sub("", _CONTROL.sub("", text or ""))
    for pat in _INJECTION:
        if pat.search(t):
            flags.append(pat.pattern[:40])
            t = pat.sub("[removed]", t)
    t = t.replace("<", "‹").replace(">", "›")
    return t[:max_len], flags


def wrap_untrusted(text: str, source: str) -> str:
    clean, _ = sanitize_untrusted(text)
    return f'<untrusted source="{source}">\n{clean}\n</untrusted>'


def redact_pii(text: str) -> str:
    return _BD_PHONE.sub("[phone]", _EMAIL.sub("[email]", text or ""))
