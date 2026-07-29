Copy this file to `notes/YYYY-MM-DD-short-slug.md` and fill it in. Files starting
with `_` are ignored by the loader, so this one is never treated as a note.

```
---
# Choose one: decision, failure, method, client-work, or outcome
pillar: decision
# Be specific, for example: Karthik in Buzz, 2026-07-29
source:
# artifact (someone can open it), published (already public on his site or
# profile), or private (said to the team). Stated, never guessed.
source_kind: private
# Only for client-work or outcome from a private source, and only if he said so
# publishable: yes
date: 2026-07-29
---

What happened?

What did you decide, learn, or try?

Who or what did it affect?

What evidence, limitation, or unresolved question remains?
```

`source_kind` is the grade of the evidence, and it decides which pillars the note
can back:

| Grade | What it is | Can back |
|---|---|---|
| `artifact` | someone outside can open it: a commit, public code, a demo | `client-work` |
| `published` | already public in his own words: site, CV, profile | any pillar |
| `private` | said to the team, not to the public | judgment pillars; `client-work` and `outcome` only with `publishable: yes` |

`outcome` never accepts `artifact`. A commit shows a change was made, not that it
helped anyone.

The grade is stated, never inferred. A `source:` that looks like a URL does not
make a note `published`. That is how "he says so" quietly becomes "someone
checked".

The four questions are prompts, not required sections. Delete any that do not
apply. Rough, short answers are enough; do not add a tidy lesson if the situation
is still unresolved.

`source` is required and cannot be empty. A note with no stated origin cannot be
graded for provenance, and in an AI-assisted workspace nothing is attributable by
default. "Karthik in Buzz, 2026-07-29" is a source. "notes" is not.

Write only what you know. The drafting step is told this note is the whole of
what it knows and that it may not add a second example, a general principle the
note does not support, or a resolution the note does not describe. Padding here
becomes an invented claim there.

You do not have to edit this file at all. If the answer already exists somewhere,
capture it and let the origin come along with it:

    printf 'what happened\n' | python3 draft.py --capture failure \
        --source "chat, msg abc123" --source-kind private

Lines starting with `#` inside the frontmatter are comments and are ignored, so the
guidance above can stay where it is useful without becoming a field.

One note is spent by one post. `draft.py --record decision --note notes/<file>.md`
marks it used so it is not written twice.
