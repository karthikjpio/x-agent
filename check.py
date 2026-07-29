#!/usr/bin/env python3
"""Draft quality gate.

Runs the mechanically checkable half of the gate in PLANS/X_GROWTH_AUTOMATION_PLAN.md §8
against a draft post, and verifies every number in the draft traces to the GATHER raw
material that produced it.

The point of the number check: a drafting model that invents "3x faster" or "40% fewer
tokens" produces a post that reads perfectly and is fiction. Numbers are the claims most
likely to be fabricated and the easiest to verify mechanically, so they get verified
mechanically instead of by a reviewer skimming.

Usage:
    python3 check.py --draft draft.md [--material raw/GATHER_2026-07-29.md]
    python3 check.py --draft draft.md --thread --json
    python3 check.py --draft draft.md --allow 280 --allow 2026

Exit codes: 0 pass, 2 gate failure, 1 hard failure (bad input).
"""

import argparse
import json
import re
import sys

GATE_FAILURE = 2

POST_LIMIT = 280

# Judgment calls a regex cannot make. Listed so they are visibly unautomated rather than
# silently dropped: a gate that quietly checks 2 of 5 rules is worse than one that says so.
HUMAN_CHECKS = [
    "One clear idea, understandable without project context.",
    "The first line creates useful tension without clickbait.",
    "The ending adds a conclusion or opens a genuine conversation.",
]

# Closing moves that ask for engagement instead of earning it.
BAIT = [
    "what do you think",
    "thoughts?",
    "agree?",
    "am i wrong",
    "let me know below",
    "drop a",
    "like and retweet",
    "rt if you",
    "who else",
    "comment below",
    "follow for more",
]

PLACEHOLDER = re.compile(r"\b(TODO|TKTK|XXX|FIXME|lorem ipsum)\b|\[[^\]]*\bfill\b[^\]]*\]", re.I)

# Karthik: emoji are fine, "but dont overkill it". Two is the line. It is a
# judgment call and it is one number to change. Worth knowing that emoji density
# is itself a documented AI marker, so a low cap serves both goals at once.
EMOJI_LIMIT = 2

# --- sounding like a model -------------------------------------------------
#
# Karthik asked for this directly: no text that sounds like AI. The signals below
# come from what current work on detection actually finds, not from taste.
#
# Negative parallelism is the strongest phrase-level tell. A Washington Post
# analysis of 328,744 ChatGPT messages found it everywhere: "it's not X, it's Y",
# "it's less about X and more about Y". Karthik's own guide bans the same
# construction independently, calling it a false contrast that mimics insight
# without containing any.
NEGATIVE_PARALLELISM = [
    # Both halves are required. "The first run did not work" is a plain negative
    # and must not trip this; the tell is the contrast, not the word "not".
    re.compile(r"\b(?:it|this|that|they|we|he|she)"
               r"(?:'s\s+not|'re\s+not|\s+is\s+not|\s+are\s+not|\s+isn't|\s+aren't"
               r"|\s+wasn't|\s+weren't|\s+was\s+not|\s+were\s+not)\s+(?:just\s+)?"
               r"[^.!?,;]{1,60}[,;]\s*(?:it|this|that|they|we)\s*(?:'s|'re|\s+is|\s+are)",
               re.I),
    re.compile(r"\bis(?:n't| not)\s+(?:just\s+)?about\b[^.!?]{1,60}\bit'?s about\b", re.I),
    re.compile(r"\bless about\b[^.!?]{1,60}\bmore about\b", re.I),
    re.compile(r"\bnot\s+(?:just\s+)?(?:[a-z]+\s+){0,3}[a-z]+\s*[,;]\s*but\b", re.I),
]

# Vocabulary whose frequency measurably jumped after ChatGPT shipped, plus the
# hype and slop words Karthik's guide names.
AI_WORDS = [
    "delve", "delves", "delving", "tapestry", "underscore", "underscores",
    "meticulous", "meticulously", "commendable", "showcase", "showcases",
    "showcasing", "surpass", "intricate", "pivotal", "realm", "testament",
    "leverage", "leveraging", "robust", "comprehensive", "cutting-edge",
    "seamless", "seamlessly", "landscape", "elevate", "boasts",
    "game-changer", "game changer", "revolutionary", "supercharge", "unlock",
    "thrilled", "delighted", "excited to announce", "in today's fast-paced world",
]

# Connectives that signal essay scaffolding rather than a person talking.
AI_TRANSITIONS = [
    "in conclusion", "furthermore", "moreover", "it is important to note",
    "it's important to note", "on the one hand", "while some may argue",
    "in the ever-evolving", "let's dive in", "at the end of the day",
    "when it comes to",
]

SENTENCE_SPLIT = re.compile(r"[.!?]+(?:\s+|$)")

# Cadence uniformity is reported as the tell that survives longest across prompt
# rewrites: sentence after sentence landing on the same length. Karthik's guide
# says the same thing in his own words, that uniform rhythm is itself a tell now
# and the fix is a five-word sentence next to a thirty-word one. Two independent
# sources agreeing is why this is checked rather than left to taste.
MIN_SENTENCES_FOR_CADENCE = 4
MIN_LENGTH_SPREAD = 5.0


def sentence_lengths(post):
    return [len(s.split()) for s in SENTENCE_SPLIT.split(post) if s.split()]


def stdev(values):
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5

# Numbers, normalised: 1,200 -> 1200, 40% -> 40, trailing sentence period dropped.
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

EMOJI_RANGES = [
    (0x1F300, 0x1FAFF),  # pictographs, emoticons, symbols, extended-A
    (0x1F000, 0x1F02F),  # mahjong/dominoes
    (0x2600, 0x27BF),    # misc symbols + dingbats
    (0xFE0F, 0xFE0F),    # variation selector-16
    (0x2190, 0x21FF),    # arrows, commonly used decoratively
]


def is_emoji(ch):
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in EMOJI_RANGES)


def normalise_numbers(text):
    return {m.group(0).replace(",", "").rstrip(".") for m in NUMBER.finditer(text)}


def posts(text, thread):
    """Split a draft into individual posts. Threads separate posts with a --- line."""
    parts = re.split(r"^\s*---\s*$", text, flags=re.M) if thread else [text]
    return [p.strip() for p in parts if p.strip()]


def check(draft, material=None, thread=False, allow=()):
    """Return a list of {rule, severity, detail} findings. Empty means the draft passes."""
    found = []

    def fail(rule, detail):
        found.append({"rule": rule, "severity": "fail", "detail": detail})

    def warn(rule, detail):
        found.append({"rule": rule, "severity": "warn", "detail": detail})

    chunks = posts(draft, thread)
    if not chunks:
        fail("empty", "draft is empty")
        return found

    for i, post in enumerate(chunks, 1):
        where = "post %d: " % i if thread else ""

        if len(post) > POST_LIMIT:
            fail("length", "%s%d chars, limit %d" % (where, len(post), POST_LIMIT))

        emojis = [ch for ch in post if is_emoji(ch)]
        if len(emojis) > EMOJI_LIMIT:
            fail("emoji", "%s%d emoji (%s), limit %d. Emoji are fine, overkill is not, "
                 "and density is itself an AI marker."
                 % (where, len(emojis), " ".join(sorted(set(emojis))), EMOJI_LIMIT))

        if "—" in post or "–" in post:
            fail("em_dash", "%sem/en dash present. Hard rule, stated by Karthik: "
                 "anywhere, ever." % where)

        low = post.lower()
        for phrase in BAIT:
            if phrase in low:
                fail("engagement_bait", "%s%r — gate rule 5" % (where, phrase))

        m = PLACEHOLDER.search(post)
        if m:
            fail("placeholder", "%sunfilled placeholder %r" % (where, m.group(0)))

        tags = re.findall(r"(?<!\w)#\w+", post)
        if tags:
            warn("hashtag", "%s%s, not present in the observed corpus"
                 % (where, " ".join(tags)))

        for pattern in NEGATIVE_PARALLELISM:
            hit = pattern.search(post)
            if hit:
                fail("negative_parallelism",
                     "%s%r. The single most reported AI phrase pattern. State the "
                     "thing you mean instead of contrasting it with what it isn't."
                     % (where, hit.group(0).strip()))
                break

        words = set(re.findall(r"[a-z'-]+", low))
        hits = sorted(w for w in AI_WORDS if (w in words if " " not in w else w in low))
        if hits:
            fail("ai_vocabulary",
                 "%s%s. Words whose use measurably jumped after ChatGPT shipped, or "
                 "hype Karthik's guide bans." % (where, ", ".join(repr(h) for h in hits)))

        scaffolding = sorted(t for t in AI_TRANSITIONS if t in low)
        if scaffolding:
            fail("ai_transition",
                 "%s%s. Essay scaffolding, not a person talking."
                 % (where, ", ".join(repr(s) for s in scaffolding)))

        lengths = sentence_lengths(post)
        if len(lengths) >= MIN_SENTENCES_FOR_CADENCE:
            spread = stdev(lengths)
            if spread < MIN_LENGTH_SPREAD:
                warn("uniform_cadence",
                     "%ssentence lengths %s, spread %.1f. Cadence uniformity is the AI "
                     "tell that survives longest. Put a short sentence next to a long one."
                     % (where, lengths, spread))

    # Number check runs across the whole draft, not per post: a thread may introduce a
    # figure in post 1 and refer back to it later.
    claimed = normalise_numbers(draft)
    if material is None:
        if claimed:
            warn("unverified_numbers",
                 "no --material given, so %s could not be traced to source"
                 % ", ".join(sorted(claimed)))
    else:
        supported = normalise_numbers(material) | {str(a).replace(",", "") for a in allow}
        orphans = sorted(claimed - supported, key=lambda x: (len(x), x))
        if orphans:
            fail("unsupported_number",
                 "%s not found in the raw material — gate rule 3. Cite it or cut it "
                 "(--allow to whitelist a known-good figure)." % ", ".join(orphans))

    return found


def report(found, thread):
    lines = []
    fails = [f for f in found if f["severity"] == "fail"]
    warns = [f for f in found if f["severity"] == "warn"]

    for f in fails:
        lines.append("FAIL  %-19s %s" % (f["rule"], f["detail"]))
    for f in warns:
        lines.append("warn  %-19s %s" % (f["rule"], f["detail"]))

    if fails:
        lines.append("")
        lines.append("%d blocking issue(s). Draft does not enter the queue." % len(fails))
    else:
        lines.append("Automated checks pass.")
        lines.append("")
        lines.append("Still requires a human read — these are not automated:")
        for c in HUMAN_CHECKS:
            lines.append("  [ ] %s" % c)
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Run the draft quality gate.")
    p.add_argument("--draft", required=True, help="path to the draft, or - for stdin")
    p.add_argument("--material", help="GATHER file the draft was written from")
    p.add_argument("--thread", action="store_true", help="draft is a thread, posts split by ---")
    p.add_argument("--allow", action="append", default=[],
                   help="a number that is known-good but absent from the material")
    p.add_argument("--json", action="store_true", dest="as_json")
    args = p.parse_args()

    try:
        draft = sys.stdin.read() if args.draft == "-" else open(args.draft).read()
        material = open(args.material).read() if args.material else None
    except OSError as e:
        print("check: %s" % e, file=sys.stderr)
        return 1

    found = check(draft, material, args.thread, args.allow)
    blocking = [f for f in found if f["severity"] == "fail"]

    if args.as_json:
        print(json.dumps({"pass": not blocking, "findings": found,
                          "human_checks": HUMAN_CHECKS}, indent=2))
    else:
        print(report(found, args.thread))

    return GATE_FAILURE if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
