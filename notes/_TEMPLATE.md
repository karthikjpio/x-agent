Copy this file to `notes/YYYY-MM-DD-short-slug.md` and fill it in. Files starting
with `_` are ignored by the loader, so this one is never treated as a note.

```
---
# Choose one: decision, failure, or method
pillar: decision
# Be specific, for example: Karthik in Buzz, 2026-07-29
source:
date: 2026-07-29
---

What happened?

What did you decide, learn, or try?

Who or what did it affect?

What evidence, limitation, or unresolved question remains?
```

`pillar` must be one of the three judgment pillars. `client-work` and `outcome`
assert that something shipped, so they are sourced from commits and cannot be
written by hand here.

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

    printf 'what happened\n' | python3 draft.py --capture failure --source "chat, msg abc123"

Lines starting with `#` inside the frontmatter are comments and are ignored, so the
guidance above can stay where it is useful without becoming a field.

One note is spent by one post. `draft.py --record decision --note notes/<file>.md`
marks it used so it is not written twice.
