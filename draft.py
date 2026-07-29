#!/usr/bin/env python3
"""Loop 2: DRAFT.

Picks which pillar to write today, assembles the source that grounds it, and
emits a fully-specified prompt for the generation step.

The generation call is deliberately not in here. Everything above it is
deterministic and testable without a model or an API key: which pillar is due,
whether a source exists to ground it, and what the writer is allowed to claim.
That is the half that decides whether a post is honest, so that is the half
that gets tests.

**Every pillar needs a source.** Two kinds:

- Commit-backed pillars (client work, client outcome) need a GATHER file with
  real commits in the window.
- Judgment pillars (decision, failure, method) need a note in `notes/` — a
  decision log entry, a project note, or an answer Karthik gave in chat.

A model that refuses to invent a shipment will still happily invent a very
plausible opinion. An empty commit window plus a generic prompt is not a
smaller version of the problem, it is the same one. So a pillar with no source
is not eligible, and a day with no eligible pillar produces exit 3 rather than
a draft.

Pillar rotation is PLANS/X_GROWTH_AUTOMATION_PLAN.md §12.2; the grounding rule
and shape notes are §12.4; voice rules are §8.

Usage:
    python3 draft.py --material raw/GATHER_2026-07-29.md
    python3 draft.py --pillar failure
    python3 draft.py --sources                   # what is available today
    python3 draft.py --record decision --note notes/2026-07-29-approval.md

Exit codes: 0 ok, 3 nothing to write today, 1 hard failure.
"""

import argparse
import datetime as dt
import json
import os
import sys

NOTHING_DUE = 3

HERE = os.path.dirname(os.path.abspath(__file__))
WINDOW_DAYS = 7

# §12.2 quotas. `needs_material` marks pillars that assert a specific thing was
# shipped: they require a commit to point at. The rest require a note.
PILLARS = [
    {
        "key": "client-work",
        "name": "Shipping client work with agents",
        "quota": 2,
        "needs_material": True,
        "proves": "AI-native delivery on production client work",
        "shape": ("The constraint you were working under, what you and the agent each "
                  "did, how you verified it before it went live, and what shipped. The "
                  "human verification step is the point, not a footnote."),
    },
    {
        "key": "decision",
        "name": "Decision + tradeoff, explained plainly",
        "quota": 2,
        "needs_material": False,
        "proves": "Translating a technical tradeoff for engineers and executives",
        "shape": ("The choice, who it affected, the option you rejected, and what the "
                  "choice cost or bought. No jargon a founder wouldn't use."),
    },
    {
        "key": "outcome",
        "name": "Client outcome",
        "quota": 1,
        "needs_material": True,
        "proves": "Customer empathy and measurable outcomes",
        "shape": ("Problem, constraint, result. Never infer a business result from a "
                  "commit. If the result was observed, state it. If it was not, say "
                  "what you will measure instead."),
    },
    {
        "key": "failure",
        "name": "Failure + lesson",
        "quota": 1,
        "needs_material": False,
        "proves": "Judgment",
        "shape": ("A specific failure and what it cost. If it is still unresolved, say "
                  "so. Do not manufacture a clean lesson or a changed behaviour that "
                  "has not happened yet."),
    },
    {
        "key": "method",
        "name": "Reusable method",
        "quota": 1,
        "needs_material": False,
        "proves": "Accelerators and best practices that scale",
        "shape": ("A workflow someone else can lift, the context where it actually "
                  "worked, and one place it does not. Without both it is generic "
                  "advice."),
    },
]

BY_KEY = {p["key"]: p for p in PILLARS}

# §8. Enforced mechanically by check.py after generation; repeated to the writer
# so drafts arrive clean rather than getting bounced.
VOICE_RULES = [
    "No emoji. Zero appear in ~50 messages of his own writing.",
    "No em dashes or en dashes (provisional rule, see plan §8).",
    "Short sentences. Cold open: no greeting, no throat-clearing.",
    "Plain language, direct claims. State a thing rather than building up to it.",
    "No hashtags. No engagement bait: no 'thoughts?', no 'what do you think'.",
    "Under 280 characters for a single post.",
    "Every number must appear in the source above. If it is not there, cut it.",
]


class DraftError(Exception):
    pass


# --- sources -----------------------------------------------------------------

def parse_note(text, path):
    """Parse a note file: `---` frontmatter, then the body.

    Requires `pillar` and `source`. `source` is where the content came from —
    a note with no stated origin cannot be graded for provenance, and an
    ungraded source is exactly how agent prose ends up published as his.

    `#` lines in the frontmatter are comments. The template carries its
    instructions inline, and a copied instruction must not become a key.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise DraftError("%s: missing --- frontmatter" % path)
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise DraftError("%s: unterminated frontmatter" % path)

    meta = {}
    for line in lines[1:end]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise DraftError("%s: bad frontmatter line %r" % (path, line))
        k, v = line.split(":", 1)
        meta[k.strip()] = v.strip()

    for field in ("pillar", "source"):
        if not meta.get(field):
            raise DraftError("%s: frontmatter needs a non-empty %r" % (path, field))
    if meta["pillar"] not in BY_KEY:
        raise DraftError("%s: unknown pillar %r" % (path, meta["pillar"]))
    if BY_KEY[meta["pillar"]]["needs_material"]:
        raise DraftError("%s: %s is commit-backed and cannot be sourced from a note"
                         % (path, meta["pillar"]))

    body = "\n".join(lines[end + 1:]).strip()
    if not body:
        raise DraftError("%s: note has frontmatter but no body" % path)

    return {"path": path, "pillar": meta["pillar"], "source": meta["source"],
            "date": meta.get("date", ""), "body": body}


def load_notes(notes_dir):
    """Load every note in the directory. A missing directory is not an error.

    Files starting with `_` are skipped so the template can live next to real
    notes without being parsed as one.
    """
    if not os.path.isdir(notes_dir):
        return []
    notes = []
    for name in sorted(os.listdir(notes_dir)):
        if not name.endswith(".md") or name.startswith("_"):
            continue
        path = os.path.join(notes_dir, name)
        try:
            with open(path) as f:
                notes.append(parse_note(f.read(), path))
        except OSError as e:
            raise DraftError("cannot read %s: %s" % (path, e))
    return notes


def capture_note(notes_dir, pillar, source, body, today):
    """Write a note from an answer given somewhere else, and return its path.

    Editing markdown on disk every day is friction that ends with three pillars
    permanently dark. This takes the answer as it was actually given — in chat,
    in a message with an id — and records it with that origin attached, so
    provenance comes from how the note was made rather than from someone
    remembering to type it.

    Validation runs through parse_note on the composed text: one set of rules,
    no second implementation to drift.
    """
    text = "---\npillar: %s\nsource: %s\ndate: %s\n---\n\n%s\n" % (
        pillar, source, today.isoformat(), (body or "").strip())
    parse_note(text, "<capture>")   # rejects bad pillar, empty source, empty body

    os.makedirs(notes_dir, exist_ok=True)
    stem = "%s-%s" % (today.isoformat(), pillar)
    path = os.path.join(notes_dir, stem + ".md")
    n = 2
    while os.path.exists(path):     # never clobber an unspent note
        path = os.path.join(notes_dir, "%s-%d.md" % (stem, n))
        n += 1
    with open(path, "w") as f:
        f.write(text)
    return path


def has_material(text):
    """A GATHER file with no commits says so in its own heading."""
    return text is not None and "## No public commits in this window" not in text


def unused_notes(notes, history):
    spent = {row.get("note") for row in history if row.get("note")}
    return [n for n in notes if n["path"] not in spent]


def pick_note(notes, pillar_key):
    """Oldest unused note first, so a backlog drains in the order it was written."""
    candidates = [n for n in notes if n["pillar"] == pillar_key]
    candidates.sort(key=lambda n: (n["date"], n["path"]))
    return candidates[0] if candidates else None


def available(material, notes):
    """The set of pillar keys that have a source right now."""
    keys = set()
    for p in PILLARS:
        if p["needs_material"]:
            if has_material(material):
                keys.add(p["key"])
        elif pick_note(notes, p["key"]):
            keys.add(p["key"])
    return keys


# --- history -----------------------------------------------------------------

def load_history(path):
    """Return a list of {date, pillar, note?}. A missing file is not an error."""
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        raise DraftError("cannot read history %s: %s" % (path, e))


def record(path, pillar_key, today, note=None):
    if pillar_key not in BY_KEY:
        raise DraftError("unknown pillar %r (expected one of %s)"
                         % (pillar_key, ", ".join(BY_KEY)))
    history = load_history(path)
    row = {"date": today.isoformat(), "pillar": pillar_key}
    if note:
        row["note"] = note
    history.append(row)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(history, f, indent=2)
    return history


def recent(history, today, days=WINDOW_DAYS):
    """History entries inside the trailing window, ignoring unparseable rows."""
    cutoff = today - dt.timedelta(days=days)
    out = []
    for row in history:
        try:
            when = dt.date.fromisoformat(row["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if cutoff < when <= today:
            out.append((when, row.get("pillar")))
    return out


# --- selection ---------------------------------------------------------------

def select(history, today, available_keys):
    """Pick the pillar with the largest unmet quota that has a source.

    Returns (pillar, reason) or (None, reason). A pillar with no source is not
    eligible at all: an empty window is a reason to write something else, never
    a reason to invent a receipt or an opinion.
    """
    window = recent(history, today)
    counts = {}
    last_used = {}
    for when, key in window:
        counts[key] = counts.get(key, 0) + 1
        if key not in last_used or when > last_used[key]:
            last_used[key] = when

    eligible = []
    for p in PILLARS:
        if p["key"] not in available_keys:
            continue
        deficit = p["quota"] - counts.get(p["key"], 0)
        if deficit <= 0:
            continue
        # Biggest deficit first, then least recently used. Unused pillars sort
        # ahead of used ones.
        staleness = (today - last_used[p["key"]]).days if p["key"] in last_used else 10**6
        eligible.append((-deficit, -staleness, PILLARS.index(p), p))

    if not eligible:
        if not available_keys:
            return None, ("no source for any pillar: no commits in the window and no "
                          "unused notes")
        unmet = [p["key"] for p in PILLARS
                 if p["quota"] - counts.get(p["key"], 0) > 0]
        if unmet:
            return None, ("the pillars still under quota (%s) have no source today"
                          % ", ".join(unmet))
        return None, "every pillar has met its weekly quota for the trailing 7 days"

    eligible.sort(key=lambda t: t[:3])
    chosen = eligible[0][3]
    return chosen, "%d of %d done in the trailing %d days" % (
        counts.get(chosen["key"], 0), chosen["quota"], WINDOW_DAYS)


# --- prompt ------------------------------------------------------------------

def build_prompt(pillar, reason, material=None, note=None):
    if pillar["needs_material"]:
        if not has_material(material):
            raise DraftError("%s needs commit material" % pillar["key"])
    elif note is None:
        raise DraftError("%s needs a note to ground it" % pillar["key"])

    out = []
    out.append("Write one X post for Karthik Jp (@karthikjpIO).")
    out.append("")
    out.append("Audience: hiring managers and engineers at AI companies. He is looking")
    out.append("for a forward-deployed engineer or AI consultant role. Every post is an")
    out.append("application asset: it should make a reader think he can understand a")
    out.append("business problem, make a sound technical call, and ship the result.")
    out.append("")
    out.append("## Today's pillar: %s" % pillar["name"])
    out.append("")
    out.append("Selected because: %s." % reason)
    out.append("Proves: %s" % pillar["proves"])
    out.append("Shape: %s" % pillar["shape"])
    out.append("")
    out.append("## Source")
    out.append("")

    if pillar["needs_material"]:
        out.append("This pillar asserts that something shipped. Every claim must trace to")
        out.append("a commit below. Do not describe work that is not in this file.")
        out.append("")
        out.append(material.strip())
    else:
        out.append("Origin: %s (`%s`)" % (note["source"], note["path"]))
        out.append("")
        out.append("This pillar makes a judgment claim, not a shipping claim. The note")
        out.append("below is the whole of what you know. Write from it. Do not add a")
        out.append("second example, a general principle it does not support, or a")
        out.append("resolution it does not describe.")
        out.append("")
        out.append(note["body"])
        if material and has_material(material):
            out.append("")
            out.append("Recent commits, for background only. Not a licence to claim a")
            out.append("receipt or to widen the note beyond what it says:")
            out.append("")
            out.append(material.strip())

    out.append("")
    out.append("## Voice")
    out.append("")
    out.append("check.py enforces the mechanical half of this list after you write. The")
    out.append("rules are here too so drafts arrive clean instead of bouncing.")
    out.append("")
    for rule in VOICE_RULES:
        out.append("- %s" % rule)

    out.append("")
    out.append("## Output")
    out.append("")
    out.append("Return the post text and nothing else. No preamble, no options, no")
    out.append("explanation. It will be run through the quality gate as-is.")
    return "\n".join(out) + "\n"


def latest_material(raw_dir):
    if not os.path.isdir(raw_dir):
        return None
    files = sorted(f for f in os.listdir(raw_dir) if f.startswith("GATHER_"))
    return os.path.join(raw_dir, files[-1]) if files else None


def describe_sources(material, notes, history):
    fresh = unused_notes(notes, history)
    lines = ["Sources available today:", ""]
    for p in PILLARS:
        if p["needs_material"]:
            state = "commits in window" if has_material(material) else "NO COMMITS"
        else:
            n = pick_note(fresh, p["key"])
            state = ("note: %s" % os.path.basename(n["path"])) if n else "NO NOTE"
        lines.append("  %-12s %s" % (p["key"], state))
    lines.append("")
    lines.append("Judgment pillars need a note in notes/ with `pillar:` and `source:`")
    lines.append("frontmatter. Without one they are not eligible and DRAFT will not")
    lines.append("generate an opinion to fill the gap.")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Choose today's pillar and build the prompt.")
    p.add_argument("--material", help="GATHER file (default: newest in raw/)")
    p.add_argument("--notes", default=os.path.join(HERE, "notes"))
    p.add_argument("--pillar", help="override the rotation and force a pillar")
    p.add_argument("--history", default=os.path.join(HERE, "state", "history.json"))
    p.add_argument("--record", metavar="PILLAR",
                   help="append a shipped post to history and exit")
    p.add_argument("--note", help="note path to mark spent, with --record")
    p.add_argument("--sources", action="store_true",
                   help="report what is available today and exit")
    p.add_argument("--capture", metavar="PILLAR",
                   help="write a note for PILLAR from stdin and exit")
    p.add_argument("--source", metavar="ORIGIN",
                   help="provenance for --capture, e.g. 'Karthik in Buzz, event abc123'")
    p.add_argument("--date", help="treat this ISO date as today (for testing)")
    args = p.parse_args()

    try:
        today = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
        history = load_history(args.history)

        if args.record:
            record(args.history, args.record, today, args.note)
            print("recorded %s on %s" % (args.record, today.isoformat()))
            return 0

        if args.capture:
            if not args.source:
                raise DraftError("--capture needs --source: where did this come from?")
            path = capture_note(args.notes, args.capture, args.source,
                                sys.stdin.read(), today)
            print("wrote %s" % path)
            return 0

        path = args.material or latest_material(os.path.join(HERE, "raw"))
        material = open(path).read() if path else None
        fresh = unused_notes(load_notes(args.notes), history)

        if args.sources:
            print(describe_sources(material, fresh, history))
            return 0

        if args.pillar:
            if args.pillar not in BY_KEY:
                raise DraftError("unknown pillar %r (expected one of %s)"
                                 % (args.pillar, ", ".join(BY_KEY)))
            pillar, reason = BY_KEY[args.pillar], "forced with --pillar"
            if args.pillar not in available(material, fresh):
                raise DraftError(
                    "%s has no source today: %s" % (
                        args.pillar,
                        "no commits in the window" if pillar["needs_material"]
                        else "no unused note in %s" % args.notes))
        else:
            pillar, reason = select(history, today, available(material, fresh))

        note = None if pillar is None or pillar["needs_material"] else \
            pick_note(fresh, pillar["key"])

        if pillar is not None:
            prompt = build_prompt(pillar, reason, material, note)
    except (DraftError, OSError) as e:
        print("draft: %s" % e, file=sys.stderr)
        return 1

    if pillar is None:
        print("draft: nothing to write today — %s" % reason, file=sys.stderr)
        return NOTHING_DUE

    sys.stdout.write(prompt)
    return 0


if __name__ == "__main__":
    sys.exit(main())
