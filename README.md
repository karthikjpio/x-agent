# x-agent

An agent that drafts posts about my work, and refuses to write a claim it has no source
for.

The interesting part is not the drafting. Any model writes a plausible post. The problem
is that a plausible post about work you did not do is indistinguishable from a real one
until someone checks, and nobody checks. So this repo is built around the checking.

## The failure it exists to prevent

A previous version of this system produced 19 drafts and shipped 0 posts in 10 days.
Two causes: the approval step lived on a `localhost` service that was usually not
running, and the default when a draft was not approved was to do nothing. A pipeline
whose failure mode is silence looks healthy right up until you count the output.

The second failure is subtler and worse. On a day with no material, a generator will
happily write a convincing ship log about nothing. That is not a bug you notice from
inside the pipeline, because the output looks exactly like the good output.

## Design

Four properties, each of which cost something to get:

**Empty is a result, not an error.** `gather.py` exits `3` when there is no material in
the window, and the raw-material file it writes says so in its own text. `draft.py` exits
`3` on a day it has nothing to write from. Neither one is allowed to fill the gap. A
pipeline that reports a clean run on a day it produced nothing real is worse than one that
stops.

**Every claim type needs its own source, including opinions.** The first version only
guarded shipping claims: no commit, no "here is what I shipped". That left the larger
hole open. A model that refuses to invent a receipt will happily invent a plausible
*decision*, *failure*, or *lesson* from a generic prompt, and that post is harder to catch
because there is no number in it to check. So the three judgment pillars are sourced too,
from a dated note in `notes/` with a stated origin. No note, not eligible. The prompt tells
the writer that the note is the whole of what it knows and that it may not add a second
example, a broader principle, or a resolution the note does not describe.

**Evidence is graded, and the grade follows the claim rather than the storage.** Requiring
a commit for every delivery claim sounds strict and is actually just wrong: most of what I
have shipped was built for clients and lives behind their firewall, and none of it has a
public commit. Meanwhile a commit proves a change was made and nothing at all about whether
it helped anyone. So a source carries one of three grades:

| Grade | What it is | Can back |
|---|---|---|
| `artifact` | someone outside can open it: a commit, public code, a demo | delivery claims |
| `published` | already public in my own words: site, CV, profile | any claim, restated as mine |
| `private` | said to the team, not to the public | judgment; delivery only if I mark it publishable |

The grade is stated by whoever supplies the source and is never inferred from the text. A
`source:` that looks like a URL does not make a note `published`. That inference is exactly
how "he says so" turns into "someone checked". The grade travels into the prompt with its
own rules, so a published account cannot be written up as though it were independently
verified.

**Numbers are verified, not trusted.** `check.py` extracts every number in a draft and
requires it to appear in the raw material that draft was written from. `87%` in a post
with no `87` in the source is a blocking failure, not a style note. Numbers are the
claims most likely to be invented and the easiest to verify mechanically, so they get
verified mechanically.

**Unautomated checks are listed, not skipped.** Three of the five gate rules are judgment
calls ("one clear idea", "the first line creates useful tension"). The gate prints them
as an explicit human checklist on every pass. A gate that silently enforces 2 of 5 rules
while reporting "pass" is worse than no gate, because it transfers confidence it has not
earned.

## Use

```console
$ python3 gather.py --days 14                 # -> raw/GATHER_2026-07-29.md, exit 3 if empty
$ python3 draft.py --sources                  # what has a source today, per pillar
$ python3 draft.py                            # -> the prompt, or exit 3 with the reason
$ python3 draft.py --record failure --note notes/2026-07-29-gate-bug.md
$ python3 check.py --draft draft.md --material raw/GATHER_2026-07-29.md
$ python3 check.py --draft thread.md --thread --json
$ python3 -m unittest test_draft test_check -v
```

A note can also be captured from an answer given somewhere else, with the origin attached
by construction rather than by remembering to type it:

```console
$ printf 'The staging deploy broke because...\n' \
    | python3 draft.py --capture failure --source "Karthik in chat, msg abc123" \
      --source-kind private
wrote notes/2026-07-29-failure.md
```

`--source` and `--source-kind` are both required, and validation runs through the same
parser as a hand-written note, so a captured note cannot skip a rule a typed one has to
follow.

Notes live in `notes/`. See `notes/_TEMPLATE.md` for the format; the short version is
`pillar:`, a non-empty `source:`, and a `source_kind:`, then whatever actually happened.
One note is spent by one post, so a backlog drains oldest first instead of the same story
getting written twice.

No dependencies. Python 3 standard library only. `gather.py` runs unauthenticated at
about 8 requests per pass against GitHub's 60/hr anonymous cap; set `GITHUB_TOKEN` to
raise it and to include private repos.

## Voice rules are versioned, and their evidence is graded

The gate enforces "no emoji" and "no em dashes". Those came from observation, and they
carry different confidence:

- **No emoji** is well supported. Zero appear across roughly 50 messages of my own writing.
- **No em dashes** is provisional. Em dashes were removed from a live landing page, but
  the commit that did it was AI co-authored, so the instruction cannot be attributed to me
  with confidence. It is a reasonable default held until real approval diffs confirm or
  kill it.

That distinction is the point. In a workspace where most artifacts are AI-assisted,
"someone wrote this" is not the same as "I wrote this", and a voice model trained on the
difference learns the wrong person. Every rule here records which corpus it came from and
how strong that corpus is.

## What is deliberately not in this repo

The voice-calibration corpus. Deriving writing style from my own messages means quoting
them, including typos and things said in frustration in private channels. That analysis
stays out of a public repo; only the resulting rules ship, with their evidence grade.

## Status

`gather.py`, `draft.py`, and `check.py` are done and tested: 106 tests, no dependencies.

The generation call itself is not wired. `draft.py` emits a fully specified prompt and
stops. That is a real boundary rather than an unfinished edge: everything that decides
whether a post is honest, which pillar is due, whether a source exists, and what the
writer is allowed to claim, is deterministic and testable without a model. The model call
is a thin adapter on top of it, and I would rather ship the tested half than an untested
integration.
