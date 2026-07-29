# x-agent

I built an agent that drafts my X posts based on my current projects and git commits,
which would also refuse to write a claim it cannot find a source for.

The best part is not drafting, any model can do that. A post like that is
indistinguishable from a real one until someone checks, and nobody checks. So this repo
is built around the checking.

The reason I care: the first run of my due diligence agent invented two competitors that
don't exist. That took a week of grounding checks to fix, and it is why I don't trust an
agent output I can't trace back to a source.

## The failure it exists to prevent

A previous version of this system left **22 drafts sitting at status `pending` and one
post in the log.** I had been quoting "19 drafts, 0 posts" from a summary; the actual
`drafts.json` and `posted-log.md` say 22 and 1. A number I repeated for a week turned out
to be wrong in both directions, which is the whole argument for the gate below.

The real reason is not a clever one: I kept forgetting about it, I got busy, and **it was
too passive.** It waited on a local dashboard for me to come to it.

The sharpest version of that: it shipped with `setup-launchd.sh`, a script that would have
scheduled the daily run. **It was never run.** There is no launch agent installed and no
log directory. The automation existed as a file, which is not the same as existing.

That is a design fault, not a discipline fault. A tool that needs you to remember it, and
a scheduler that needs you to install it, both lose to everything else in your week.

The second failure is subtler. On a day with no material, a generator will happily write
a convincing ship log about nothing. That is not a bug you notice from inside the
pipeline, because the output looks exactly like the good output.

## Design

Five properties, each of which cost something to get:

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

**It should not sound like a model.** I asked for this directly and it is checked, not
left to taste. The gate blocks the contrast construction ("it's not X, it's Y"), which a
Washington Post analysis of 328,744 ChatGPT messages found to be the most reported phrase
pattern; vocabulary whose frequency measurably jumped after ChatGPT shipped (delve,
tapestry, meticulous, pivotal, seamless); and essay scaffolding (in conclusion,
furthermore, it is important to note). It also warns on **uniform cadence**, sentence
after sentence landing on the same length, which is reported as the tell that survives
longest across rewrites. The writer gets the same list before drafting, so a draft that
would bounce mostly never gets written.

**Unautomated checks are listed, not skipped.** Three of the five gate rules are judgment
calls ("one clear idea", "the first line creates useful tension"). The gate prints them
as an explicit human checklist on every pass. A gate that silently enforces 2 of 5 rules
while reporting "pass" is worse than no gate, because it transfers confidence it has not
earned.

## Use

The normal entry point is the durable pipeline:

```console
$ python3 pipeline.py run
```

It returns one JSON review card. The possible results are:

- `needs_interview`: commits exist, but the system needs Karthik's constraint,
  tradeoff and verification details before it writes.
- `awaiting_review`: a draft passed the automated gate and still needs the
  listed human checks.
- `gate_failed`: three generation attempts failed; nothing enters review.
- `skipped`: no eligible sourced claim exists today.

The review lifecycle keeps approval separate from publication:

```console
$ python3 pipeline.py approve 2026-07-29-method-abc123
$ python3 pipeline.py reject 2026-07-29-method-abc123 --feedback "Open with the failure"
$ python3 pipeline.py revise 2026-07-29-method-abc123 --feedback "Cut the last line"
$ python3 pipeline.py delivered 2026-07-29-method-abc123 --event <Buzz-event-id>
$ python3 pipeline.py published 2026-07-29-method-abc123 \
    --url https://x.com/KarthikjpIO/status/123
```

Approval never spends the source. Only `published`, with the real X URL,
records the pillar in history and spends the note. Repeated scheduler runs and
repeated lifecycle commands are idempotent.

Build posts pause for an interview. Capture the verified answer with its Buzz
event as provenance, and only add `--publishable` after Karthik explicitly says
the details may be public:

```console
$ printf 'What happened, in Karthik'\''s own words\n' \
  | python3 pipeline.py answer 2026-07-29-client-work-abc123 \
      --source "Karthik in Buzz event abc123" --publishable
$ python3 pipeline.py run
```

`workflows/daily-buzz-review.yaml` is the schedule definition used in Buzz. At
07:00 UTC on weekdays it wakes Fizz in the project channel. Fizz runs the
pipeline and posts exactly one review card or one visible blocker. The workflow
does not contain credentials and does not call X.

The individual stages remain available for debugging:

```console
$ python3 gather.py --days 14                 # -> raw/GATHER_2026-07-29.md, exit 3 if empty
$ python3 draft.py --sources                  # what has a source today, per pillar
$ python3 draft.py                            # -> the prompt, or exit 3 with the reason
$ python3 draft.py --record failure --note notes/2026-07-29-gate-bug.md
$ python3 draft.py | python3 generate.py > draft.md      # the whole loop
$ python3 check.py --draft draft.md --material raw/GATHER_2026-07-29.md
$ python3 check.py --draft thread.md --thread --json
$ python3 -m unittest test_draft test_check test_generate -v
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

The gate enforces "no em dashes" and caps emoji at two per post. Those rules came from observation, and they
carry different confidence:

- **No em dashes** is a hard rule, stated by me directly: anywhere, ever, in code and
  content alike. It was inferred first from a landing-page commit, which was a weak
  source because that commit was AI co-authored. The inference happened to be right, but
  it was right by luck until I confirmed it.
- **Emoji are capped, not banned.** This moved twice. Zero appear across roughly 50
  messages of my own writing, so the first rule was "none", which was overfitting a chat
  corpus to a publishing channel. My actual preference is that I like them and do not want
  them overdone, so the gate allows two per post. Emoji density is also a documented AI
  marker, so a low cap happens to serve both goals.

That gap between a lucky inference and a stated rule is the point. In a workspace where
most artifacts are AI-assisted, "someone wrote this" is not the same as "I wrote this",
and a voice model trained on the difference learns the wrong person. Every rule here
records which corpus it came from and how strong that corpus is.

## What is deliberately not in this repo

The voice-calibration corpus. Deriving writing style from my own messages means quoting
them, including typos and things said in frustration in private channels. That analysis
stays out of a public repo; only the resulting rules ship, with their evidence grade.

The project-specific privacy denylist is also excluded. Copy
`config/private-denylist.example.txt` to `config/private-denylist.txt` and place
private client codenames and internal resource identifiers there. Publishing
the real denylist would disclose the identifiers it protects. The privacy gate
runs on the source before generation and on the draft before review; it also
blocks common API keys, Nostr private keys, private-key blocks, and phone
numbers.

## Status

The four drafting stages and the human review lifecycle are done and tested:
150 tests, no third-party Python dependencies.

`generate.py` shells out to the `claude` CLI rather than calling an HTTP API, so it needs
no API key and no SDK: it reuses the credentials the CLI already has. The model command is
injectable, which is why the tests cover the paths that matter, an empty reply, a missing
command, a non-zero exit and a timeout, without ever calling a model.

It stays the thinnest module here on purpose. Everything that decides whether a post is
honest happens before it, and everything that decides whether a draft is publishable
happens after it.

There is deliberately no X API client, credential, or posting action in this
repository. A human publishes the approved text and gives the pipeline the post
URL afterward.
