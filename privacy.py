#!/usr/bin/env python3
"""Privacy gate for source material, prompts, drafts, and delivery cards."""

import os
import re


class PrivacyError(Exception):
    pass


SECRET_PATTERNS = [
    ("GitHub token", re.compile(r"\bgh[opsu]_[A-Za-z0-9_]{20,}\b")),
    ("API key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("Nostr private key", re.compile(r"\bnsec1[023456789acdefghjklmnpqrstuvwxyz]{40,}\b", re.I)),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("phone number", re.compile(r"(?<!\w)(?:\+\d[\d ()-]{8,}\d)(?!\w)")),
]


def load_denylist(path):
    if not path or not os.path.exists(path):
        return []
    with open(path) as f:
        return [line.strip() for line in f
                if line.strip() and not line.lstrip().startswith("#")]


def findings(text, denylist=()):
    hits = []
    low = (text or "").lower()
    for term in denylist:
        if term.lower() in low:
            hits.append("private denylist term")
    for label, pattern in SECRET_PATTERNS:
        if pattern.search(text or ""):
            hits.append(label)
    return sorted(set(hits))


def require_safe(text, denylist=(), label="content"):
    hits = findings(text, denylist)
    if hits:
        raise PrivacyError("%s blocked by privacy gate: %s" % (label, ", ".join(hits)))
    return text
