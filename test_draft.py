#!/usr/bin/env python3
"""Tests for source grounding, pillar selection, and prompt construction.

The property most of these exist to protect: no path through this module hands
the writer a prompt for a claim it has no source of an accepted grade for.

Three grades (§12.4). An inspectable artifact shows what was built. Karthik's
own published account shows what he has already said in public. Private input
grounds judgment, and only backs a delivery claim when he has marked it safe to
publish. The grade is always stated by whoever supplies the source, never
inferred from the text, because inferring it is how "he says so" turns into
"someone checked".

Run: python3 -m unittest test_draft -v
"""

import datetime as dt
import json
import os
import tempfile
import unittest

import draft

TODAY = dt.date(2026, 7, 29)

MATERIAL = """# Raw material for 2026-07-29

## `parivartane`
- **2026-07-07** `a1b2c3d` Redirect booking CTAs to WhatsApp DM
"""

EMPTY = """# Raw material for 2026-07-29

## No public commits in this window

0 commits found between 2026-07-15 and today.
"""

NOTE = """---
pillar: decision
source: Karthik in Buzz, 2026-07-29
source_kind: private
date: 2026-07-29
---
Chose one repo with a per-platform profile over two repos. Two repos meant two
copies of the voice rules drifting apart.
"""

ALL_KEYS = {p["key"] for p in draft.PILLARS}
ARTIFACT_KEYS = {p["key"] for p in draft.PILLARS if "artifact" in p["allows"]}
NOTE_ONLY_KEYS = ALL_KEYS - ARTIFACT_KEYS


def history(*pairs):
    """history(('client-work', 1), ...) -> N days ago."""
    return [{"date": (TODAY - dt.timedelta(days=ago)).isoformat(), "pillar": key}
            for key, ago in pairs]


def note(pillar="decision", source="Karthik in Buzz", date="2026-07-29",
         body="A body.", path="notes/n.md", kind="private", publishable=False):
    return {"path": path, "pillar": pillar, "source": source, "source_kind": kind,
            "publishable": publishable, "date": date, "body": body}


def frontmatter(pillar="decision", source="chat", kind="private", extra="",
                body="It broke."):
    return "---\npillar: %s\nsource: %s\nsource_kind: %s\n%s---\n\n%s\n" % (
        pillar, source, kind, extra, body)


class TestHasMaterial(unittest.TestCase):
    def test_commits_present(self):
        self.assertTrue(draft.has_material(MATERIAL))

    def test_empty_window_detected(self):
        self.assertFalse(draft.has_material(EMPTY))

    def test_missing_file_is_not_material(self):
        self.assertFalse(draft.has_material(None))


class TestNoteParsing(unittest.TestCase):
    def test_valid_note_round_trips(self):
        n = draft.parse_note(NOTE, "notes/a.md")
        self.assertEqual(n["pillar"], "decision")
        self.assertEqual(n["source"], "Karthik in Buzz, 2026-07-29")
        self.assertEqual(n["source_kind"], "private")
        self.assertFalse(n["publishable"])
        self.assertIn("per-platform profile", n["body"])

    def test_missing_source_is_rejected(self):
        # Provenance is the whole point. A note with no stated origin cannot be
        # graded, and an ungraded source is how agent prose ships as his.
        text = NOTE.replace("source: Karthik in Buzz, 2026-07-29\n", "")
        with self.assertRaises(draft.DraftError):
            draft.parse_note(text, "notes/a.md")

    def test_empty_source_is_rejected(self):
        text = NOTE.replace("source: Karthik in Buzz, 2026-07-29", "source:")
        with self.assertRaises(draft.DraftError):
            draft.parse_note(text, "notes/a.md")

    def test_missing_pillar_is_rejected(self):
        text = NOTE.replace("pillar: decision\n", "")
        with self.assertRaises(draft.DraftError):
            draft.parse_note(text, "notes/a.md")

    def test_unknown_pillar_is_rejected(self):
        text = NOTE.replace("pillar: decision", "pillar: hot-takes")
        with self.assertRaises(draft.DraftError):
            draft.parse_note(text, "notes/a.md")

    def test_body_only_whitespace_is_rejected(self):
        with self.assertRaises(draft.DraftError):
            draft.parse_note(frontmatter(body="   "), "notes/a.md")

    def test_missing_frontmatter_is_rejected(self):
        with self.assertRaises(draft.DraftError):
            draft.parse_note("just a body\n", "notes/a.md")

    def test_unterminated_frontmatter_is_rejected(self):
        with self.assertRaises(draft.DraftError):
            draft.parse_note("---\npillar: decision\nsource: chat\n", "notes/a.md")


class TestSourceGrades(unittest.TestCase):
    """§12.4. The gate follows the claim, not where the evidence lives."""

    def test_source_kind_is_required(self):
        text = NOTE.replace("source_kind: private\n", "")
        with self.assertRaises(draft.DraftError):
            draft.parse_note(text, "notes/a.md")

    def test_unknown_grade_is_rejected(self):
        with self.assertRaises(draft.DraftError):
            draft.parse_note(frontmatter(kind="trust-me"), "notes/a.md")

    def test_grade_is_never_inferred_from_a_url_shaped_source(self):
        # A source string that looks published does not make the grade
        # published. Honey's rule: state it, do not guess it.
        n = draft.parse_note(
            frontmatter(source="https://karthikjp.io", kind="private"), "notes/a.md")
        self.assertEqual(n["source_kind"], "private")

    def test_published_account_can_ground_a_delivery_claim(self):
        # The four EY systems: real production work, no public commit.
        n = draft.parse_note(
            frontmatter(pillar="client-work", source="karthikjp.io", kind="published",
                        body="Shipped due-diligence agents used by M&A teams."),
            "notes/a.md")
        self.assertEqual(n["pillar"], "client-work")

    def test_published_account_can_ground_an_outcome(self):
        n = draft.parse_note(
            frontmatter(pillar="outcome", source="karthikjavanappa.com",
                        kind="published", body="Found in seconds instead of hours."),
            "notes/a.md")
        self.assertEqual(n["pillar"], "outcome")

    def test_private_input_alone_cannot_ground_a_delivery_claim(self):
        for pillar in sorted(draft.DELIVERY_PILLARS):
            with self.assertRaises(draft.DraftError):
                draft.parse_note(frontmatter(pillar=pillar, kind="private"),
                                 "notes/a.md")

    def test_private_input_grounds_delivery_once_marked_publishable(self):
        for pillar in sorted(draft.DELIVERY_PILLARS):
            n = draft.parse_note(
                frontmatter(pillar=pillar, kind="private", extra="publishable: yes\n"),
                "notes/a.md")
            self.assertTrue(n["publishable"])

    def test_publishable_is_ignored_unless_explicitly_affirmative(self):
        for value in ("no", "false", "maybe", ""):
            with self.assertRaises(draft.DraftError):
                draft.parse_note(
                    frontmatter(pillar="outcome", kind="private",
                                extra="publishable: %s\n" % value), "notes/a.md")

    def test_an_artifact_cannot_ground_an_outcome(self):
        # A commit proves a change was made and nothing about whether it helped
        # anyone. This was in the shape note as prose while the gate let it
        # through anyway.
        self.assertNotIn("artifact", draft.BY_KEY["outcome"]["allows"])
        with self.assertRaises(draft.DraftError):
            draft.parse_note(frontmatter(pillar="outcome", kind="artifact"),
                             "notes/a.md")

    def test_an_artifact_cannot_ground_a_judgment_pillar(self):
        # A commit list does not contain the reasoning behind a decision.
        for pillar in ("decision", "failure", "method"):
            with self.assertRaises(draft.DraftError):
                draft.parse_note(frontmatter(pillar=pillar, kind="artifact"),
                                 "notes/a.md")

    def test_an_artifact_can_ground_a_delivery_claim(self):
        n = draft.parse_note(
            frontmatter(pillar="client-work", source="github.com/x/y commit abc",
                        kind="artifact"), "notes/a.md")
        self.assertEqual(n["source_kind"], "artifact")


class TestFrontmatterComments(unittest.TestCase):
    """The template carries its instructions inline, so a copied instruction
    must not become a key or a hard failure."""

    def test_comment_lines_are_ignored(self):
        text = ("---\n"
                "# Choose one: decision, failure, or method\n"
                "pillar: decision\n"
                "# Be specific, for example: Karthik in Buzz, 2026-07-29\n"
                "source: Karthik in Buzz, 2026-07-29\n"
                "source_kind: private\n"
                "---\n\nIt broke.\n")
        n = draft.parse_note(text, "notes/a.md")
        self.assertEqual(n["pillar"], "decision")
        self.assertEqual(n["source"], "Karthik in Buzz, 2026-07-29")

    def test_a_comment_without_a_colon_is_not_a_parse_error(self):
        text = ("---\n# choose one\npillar: failure\nsource: chat\n"
                "source_kind: private\n---\n\nIt broke.\n")
        self.assertEqual(draft.parse_note(text, "notes/a.md")["pillar"], "failure")

    def test_a_commented_out_source_does_not_count_as_a_source(self):
        # Copying the template without filling it in must fail, not pass with
        # the example value from the comment.
        text = ("---\n# for example: Karthik in Buzz\npillar: decision\n"
                "source:\nsource_kind: private\n---\n\nIt broke.\n")
        with self.assertRaises(draft.DraftError):
            draft.parse_note(text, "notes/a.md")

    def test_the_shipped_template_round_trips_once_filled_in(self):
        # Guards the template and the parser against drifting apart.
        path = os.path.join(os.path.dirname(os.path.abspath(draft.__file__)),
                            "notes", "_TEMPLATE.md")
        with open(path) as f:
            inner = f.read().split("```")[1]
        filled = (inner.replace("source:", "source: Karthik in Buzz", 1).strip()
                  + "\nIt broke.\n")
        self.assertEqual(draft.parse_note(filled, "notes/a.md")["pillar"], "decision")
        with self.assertRaises(draft.DraftError):
            draft.parse_note(inner.strip(), "notes/a.md")


class TestCapture(unittest.TestCase):
    def test_captured_note_is_loadable_by_the_normal_path(self):
        with tempfile.TemporaryDirectory() as d:
            path = draft.capture_note(d, "failure", "Karthik in Buzz, event abc123",
                                      "private", "The gate passed a blank draft.", TODAY)
            loaded = draft.load_notes(d)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["path"], path)
            self.assertEqual(loaded[0]["source"], "Karthik in Buzz, event abc123")
            self.assertEqual(loaded[0]["source_kind"], "private")
            self.assertIn("blank draft", loaded[0]["body"])
            self.assertEqual(loaded[0]["date"], TODAY.isoformat())

    def test_capture_unlocks_exactly_one_pillar(self):
        with tempfile.TemporaryDirectory() as d:
            draft.capture_note(d, "method", "Karthik in Buzz", "private",
                               "Do it this way.", TODAY)
            self.assertEqual(draft.available(EMPTY, draft.load_notes(d)), {"method"})

    def test_capture_enforces_the_same_grade_rules_as_a_typed_note(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(draft.DraftError):
                draft.capture_note(d, "outcome", "chat", "private", "It worked.", TODAY)
            self.assertEqual(os.listdir(d), [])
            path = draft.capture_note(d, "outcome", "chat", "private", "It worked.",
                                      TODAY, publishable=True)
            self.assertTrue(draft.load_notes(d)[0]["publishable"])
            self.assertTrue(os.path.exists(path))

    def test_capture_rejects_an_unknown_grade(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(draft.DraftError):
                draft.capture_note(d, "failure", "chat", "vibes", "It broke.", TODAY)

    def test_capture_rejects_an_empty_source(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(draft.DraftError):
                draft.capture_note(d, "failure", "", "private", "It broke.", TODAY)

    def test_capture_rejects_an_empty_body(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(draft.DraftError):
                draft.capture_note(d, "failure", "chat", "private", "   \n\n", TODAY)

    def test_nothing_is_written_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as d:
            for bad in [("outcome", "chat", "artifact", "x"),
                        ("failure", "", "private", "x"),
                        ("nope", "chat", "private", "x"),
                        ("failure", "chat", "private", ""),
                        ("failure", "chat", "artifact", "x")]:
                with self.assertRaises(draft.DraftError):
                    draft.capture_note(d, bad[0], bad[1], bad[2], bad[3], TODAY)
            self.assertEqual(os.listdir(d), [])

    def test_a_second_note_the_same_day_does_not_clobber_the_first(self):
        with tempfile.TemporaryDirectory() as d:
            a = draft.capture_note(d, "failure", "chat", "private", "First.", TODAY)
            b = draft.capture_note(d, "failure", "chat", "private", "Second.", TODAY)
            self.assertNotEqual(a, b)
            bodies = sorted(n["body"] for n in draft.load_notes(d))
            self.assertEqual(bodies, ["First.", "Second."])


class TestLoadNotes(unittest.TestCase):
    def test_missing_directory_is_not_an_error(self):
        self.assertEqual(draft.load_notes("/nonexistent/notes"), [])

    def test_non_markdown_and_template_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "a.md"), "w") as f:
                f.write(NOTE)
            with open(os.path.join(d, "notes.txt"), "w") as f:
                f.write("not a note")
            with open(os.path.join(d, "_TEMPLATE.md"), "w") as f:
                f.write("fill this in\n")   # deliberately not parseable
            loaded = draft.load_notes(d)
            self.assertEqual([os.path.basename(n["path"]) for n in loaded], ["a.md"])

    def test_a_malformed_note_fails_loudly(self):
        # Silently dropping it would make a pillar look sourceless for a reason
        # nobody can see.
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "bad.md"), "w") as f:
                f.write("no frontmatter here\n")
            with self.assertRaises(draft.DraftError):
                draft.load_notes(d)


class TestAvailability(unittest.TestCase):
    def test_material_alone_unlocks_only_artifact_pillars(self):
        self.assertEqual(draft.available(MATERIAL, []), ARTIFACT_KEYS)

    def test_outcome_is_not_unlocked_by_commits(self):
        self.assertNotIn("outcome", draft.available(MATERIAL, []))

    def test_a_published_note_unlocks_outcome_with_no_commits_at_all(self):
        n = note("outcome", kind="published")
        self.assertIn("outcome", draft.available(EMPTY, [n]))

    def test_notes_alone_unlock_only_their_own_pillars(self):
        self.assertEqual(draft.available(EMPTY, [note("failure")]), {"failure"})

    def test_nothing_available_is_the_empty_set(self):
        self.assertEqual(draft.available(EMPTY, []), set())
        self.assertEqual(draft.available(None, []), set())

    def test_spent_notes_are_not_available_again(self):
        n = note(path="notes/a.md")
        spent = [{"date": TODAY.isoformat(), "pillar": "decision", "note": "notes/a.md"}]
        self.assertEqual(draft.unused_notes([n], spent), [])
        self.assertEqual(draft.unused_notes([n], []), [n])

    def test_oldest_unused_note_is_picked_first(self):
        old = note(date="2026-07-01", path="notes/old.md")
        new = note(date="2026-07-29", path="notes/new.md")
        self.assertEqual(draft.pick_note([new, old], "decision")["path"], "notes/old.md")

    def test_pick_note_ignores_other_pillars(self):
        self.assertIsNone(draft.pick_note([note("failure")], "method"))

    def test_same_day_collision_suffix_still_drains_in_written_order(self):
        # capture_note names the second note of a day `<stem>-2.md`, and `-`
        # sorts before `.`, so comparing whole filenames drains the newer note
        # first. Found by writing two notes on one day and watching the wrong
        # one come back.
        first = note(date="2026-07-29", path="notes/2026-07-29-outcome.md")
        second = note(date="2026-07-29", path="notes/2026-07-29-outcome-2.md")
        picked = draft.pick_note([second, first], "decision")
        self.assertEqual(picked["path"], "notes/2026-07-29-outcome.md")

    def test_the_unsuffixed_note_wins_against_double_digit_suffixes(self):
        # Only claims what it checks: the first note of the day still sorts
        # first. Suffixes compare lexicographically, so `-10` still precedes
        # `-2`. That needs 10 notes for one pillar in one day to matter, and
        # fixing it would mean parsing the suffix, so it stands as a known edge.
        notes = [note(path="notes/a-%d.md" % i) for i in (10, 2)]
        notes.append(note(path="notes/a.md"))
        self.assertEqual(draft.pick_note(notes, "decision")["path"], "notes/a.md")


class TestSelection(unittest.TestCase):
    def test_empty_history_picks_highest_quota_pillar(self):
        pillar, _ = draft.select([], TODAY, ALL_KEYS)
        self.assertEqual(pillar["key"], "client-work")

    def test_skips_artifact_pillars_when_no_material(self):
        pillar, _ = draft.select([], TODAY, NOTE_ONLY_KEYS)
        self.assertEqual(pillar["key"], "decision")

    def test_never_returns_an_artifact_pillar_without_material(self):
        # No path through selection produces a pillar asserting a shipped thing
        # when nothing shipped. Walk the whole rotation, not one case.
        h = []
        for _ in range(12):
            pillar, _ = draft.select(h, TODAY, NOTE_ONLY_KEYS)
            if pillar is None:
                break
            self.assertNotIn(pillar["key"], ARTIFACT_KEYS)
            h.append({"date": TODAY.isoformat(), "pillar": pillar["key"]})

    def test_never_returns_a_note_only_pillar_without_a_note(self):
        # The gap Honey caught: refusing to invent a shipment while happily
        # inventing an opinion. Same walk, other direction.
        h = []
        for _ in range(12):
            pillar, _ = draft.select(h, TODAY, ARTIFACT_KEYS)
            if pillar is None:
                break
            self.assertIn(pillar["key"], ARTIFACT_KEYS)
            h.append({"date": TODAY.isoformat(), "pillar": pillar["key"]})

    def test_only_the_sourced_pillar_is_reachable(self):
        # A note for `failure` does not make `decision` or `method` eligible,
        # even though they are the same kind of pillar and further under quota.
        h = []
        for _ in range(12):
            pillar, _ = draft.select(h, TODAY, {"failure"})
            if pillar is None:
                break
            self.assertEqual(pillar["key"], "failure")
            h.append({"date": TODAY.isoformat(), "pillar": pillar["key"]})

    def test_no_source_at_all_returns_none_and_says_why(self):
        pillar, reason = draft.select([], TODAY, set())
        self.assertIsNone(pillar)
        self.assertIn("no source", reason)

    def test_unmet_pillars_without_a_source_are_reported_as_such(self):
        h = history(("decision", 1), ("decision", 2))
        pillar, reason = draft.select(h, TODAY, {"decision"})
        self.assertIsNone(pillar)
        self.assertIn("no source today", reason)
        self.assertIn("client-work", reason)

    def test_all_quotas_met_returns_none(self):
        h = history(("client-work", 1), ("client-work", 2), ("decision", 1),
                    ("decision", 2), ("outcome", 3), ("failure", 3), ("method", 4))
        pillar, reason = draft.select(h, TODAY, ALL_KEYS)
        self.assertIsNone(pillar)
        self.assertIn("quota", reason)

    def test_partly_used_quota_still_eligible(self):
        h = history(("client-work", 1), ("decision", 1), ("decision", 2),
                    ("outcome", 3), ("failure", 3), ("method", 4))
        pillar, reason = draft.select(h, TODAY, ALL_KEYS)
        self.assertEqual(pillar["key"], "client-work")
        self.assertIn("1 of 2", reason)

    def test_rotation_spreads_rather_than_draining_one_pillar(self):
        h = history(("client-work", 0))
        pillar, _ = draft.select(h, TODAY, ALL_KEYS)
        self.assertEqual(pillar["key"], "decision")

    def test_a_full_week_covers_every_pillar_to_quota(self):
        h = []
        for _ in range(7):
            pillar, _ = draft.select(h, TODAY, ALL_KEYS)
            self.assertIsNotNone(pillar)
            h.append({"date": TODAY.isoformat(), "pillar": pillar["key"]})
        counts = {}
        for row in h:
            counts[row["pillar"]] = counts.get(row["pillar"], 0) + 1
        self.assertEqual(counts, {p["key"]: p["quota"] for p in draft.PILLARS})
        self.assertIsNone(draft.select(h, TODAY, ALL_KEYS)[0])

    def test_history_outside_window_does_not_count(self):
        h = history(("client-work", 30), ("client-work", 40))
        pillar, _ = draft.select(h, TODAY, ALL_KEYS)
        self.assertEqual(pillar["key"], "client-work")

    def test_ties_break_toward_least_recently_used(self):
        h = history(("client-work", 1), ("client-work", 2),
                    ("decision", 1), ("decision", 2), ("outcome", 3),
                    ("method", 30))
        pillar, _ = draft.select(h, TODAY, ALL_KEYS)
        self.assertEqual(pillar["key"], "failure")

    def test_malformed_history_rows_are_skipped_not_fatal(self):
        h = [{"date": "not-a-date", "pillar": "decision"}, {"pillar": "decision"}, {}]
        pillar, _ = draft.select(h, TODAY, ALL_KEYS)
        self.assertEqual(pillar["key"], "client-work")


class TestPrompt(unittest.TestCase):
    def test_artifact_pillar_embeds_material_and_demands_tracing(self):
        prompt = draft.build_prompt(draft.BY_KEY["client-work"], "test", MATERIAL)
        self.assertIn("a1b2c3d", prompt)
        self.assertIn("must trace", prompt)

    def test_artifact_pillar_refuses_an_empty_window(self):
        with self.assertRaises(draft.DraftError):
            draft.build_prompt(draft.BY_KEY["client-work"], "test", EMPTY)

    def test_outcome_refuses_to_build_from_commits(self):
        with self.assertRaises(draft.DraftError):
            draft.build_prompt(draft.BY_KEY["outcome"], "test", MATERIAL)

    def test_note_only_pillar_refuses_to_build_without_a_note(self):
        with self.assertRaises(draft.DraftError):
            draft.build_prompt(draft.BY_KEY["decision"], "test", MATERIAL)

    def test_a_mismatched_note_is_refused(self):
        with self.assertRaises(draft.DraftError):
            draft.build_prompt(draft.BY_KEY["failure"], "test", None, note("decision"))

    def test_the_grade_travels_into_the_prompt(self):
        for kind in ("artifact", "published", "private"):
            pillar = draft.BY_KEY["client-work"]
            n = note("client-work", kind=kind, publishable=True)
            prompt = draft.build_prompt(pillar, "test", None, n)
            self.assertIn(draft.SOURCE_KINDS[kind]["label"], prompt)

    def test_published_grade_warns_against_implying_verification(self):
        n = note("client-work", kind="published", source="karthikjp.io")
        prompt = draft.build_prompt(draft.BY_KEY["client-work"], "test", None, n)
        self.assertIn("not independent verification", prompt)
        self.assertIn("may not add client names", prompt)
        self.assertIn("publicly inspectable", prompt)

    def test_artifact_grade_says_it_is_not_a_business_result(self):
        prompt = draft.build_prompt(draft.BY_KEY["client-work"], "test", MATERIAL)
        self.assertIn("does not show a business result", prompt)

    def test_publishable_marking_is_stated_to_the_writer(self):
        n = note("outcome", kind="private", publishable=True)
        prompt = draft.build_prompt(draft.BY_KEY["outcome"], "test", None, n)
        self.assertIn("marked this safe to publish", prompt)

    def test_note_prompt_embeds_the_note_and_its_origin(self):
        n = draft.parse_note(NOTE, "notes/a.md")
        prompt = draft.build_prompt(draft.BY_KEY["decision"], "test", EMPTY, n)
        self.assertIn("per-platform profile", prompt)
        self.assertIn("Karthik in Buzz", prompt)
        self.assertIn("notes/a.md", prompt)

    def test_note_prompt_forbids_widening_the_note(self):
        n = draft.parse_note(NOTE, "notes/a.md")
        prompt = draft.build_prompt(draft.BY_KEY["decision"], "test", EMPTY, n)
        self.assertIn("Do not", prompt)
        self.assertIn("add a second example", prompt)

    def test_note_prompt_marks_commits_as_background_only(self):
        n = draft.parse_note(NOTE, "notes/a.md")
        prompt = draft.build_prompt(draft.BY_KEY["decision"], "test", MATERIAL, n)
        self.assertIn("background only", prompt)
        self.assertIn("a1b2c3d", prompt)

    def test_background_commits_do_not_smuggle_in_their_own_instructions(self):
        # GATHER ends with "every claim must trace to a commit". True when
        # commits are the source, wrong when they are background under a note
        # of another grade, and it is the more emphatic of the two.
        material = MATERIAL + (
            "\n## Notes for drafting\n\n- Every claim in a post must trace to a "
            "commit above.\n")
        n = note("outcome", kind="published")
        prompt = draft.build_prompt(draft.BY_KEY["outcome"], "test", material, n)
        self.assertIn("a1b2c3d", prompt)
        self.assertNotIn("Notes for drafting", prompt)
        self.assertNotIn("must trace to a commit above", prompt)
        self.assertIn("provenance", prompt.lower())

    def test_background_stripping_leaves_a_plain_file_alone(self):
        self.assertEqual(draft.as_background(MATERIAL), MATERIAL.strip())

    def test_note_prompt_omits_an_empty_window_entirely(self):
        n = draft.parse_note(NOTE, "notes/a.md")
        prompt = draft.build_prompt(draft.BY_KEY["decision"], "test", EMPTY, n)
        self.assertNotIn("No public commits", prompt)

    def test_voice_rules_are_carried_into_the_prompt(self):
        n = draft.parse_note(NOTE, "notes/a.md")
        prompt = draft.build_prompt(draft.BY_KEY["decision"], "test", None, n)
        self.assertIn("em dashes", prompt)
        self.assertIn("two emoji", prompt)
        self.assertIn("Every number must appear", prompt)

    def test_the_anti_ai_rules_reach_the_writer(self):
        # The gate blocks these after the fact. Telling the writer up front is
        # what stops a draft bouncing on something it could have avoided.
        n = draft.parse_note(NOTE, "notes/a.md")
        prompt = draft.build_prompt(draft.BY_KEY["decision"], "test", None, n)
        self.assertIn("not X, it's Y", prompt)
        self.assertIn("delve", prompt)
        self.assertIn("in conclusion", prompt.lower())
        self.assertIn("Uniform cadence", prompt)

    def test_prompt_rules_stay_in_step_with_the_gate(self):
        # These two lists drifted once already: the prompt still described the
        # old universal no-emoji rule after the gate had moved on. Assert the
        # words the gate actually blocks are the words the writer is warned about.
        import check
        n = draft.parse_note(NOTE, "notes/a.md")
        prompt = draft.build_prompt(draft.BY_KEY["decision"], "test", None, n).lower()
        for word in ["delve", "tapestry", "pivotal", "seamless", "robust"]:
            self.assertIn(word, prompt, word)
        for phrase in ["in conclusion", "furthermore", "it is important to note"]:
            self.assertIn(phrase, prompt, phrase)
        self.assertTrue(all(w in check.AI_WORDS for w in
                            ["delve", "tapestry", "pivotal", "seamless", "robust"]))

    def test_shape_note_reaches_the_writer(self):
        n = note("outcome", kind="published")
        prompt = draft.build_prompt(draft.BY_KEY["outcome"], "test", None, n)
        self.assertIn("Never infer a business result", prompt)

    def test_selection_reason_is_stated(self):
        prompt = draft.build_prompt(draft.BY_KEY["client-work"], "0 of 2 done", MATERIAL)
        self.assertIn("0 of 2 done", prompt)


class TestHistoryFile(unittest.TestCase):
    def test_missing_history_is_empty_not_an_error(self):
        self.assertEqual(draft.load_history("/nonexistent/history.json"), [])

    def test_record_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "state", "history.json")
            draft.record(path, "failure", TODAY)
            draft.record(path, "method", TODAY)
            loaded = draft.load_history(path)
            self.assertEqual([r["pillar"] for r in loaded], ["failure", "method"])

    def test_recording_a_note_spends_it(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.json")
            n = note(path="notes/a.md")
            draft.record(path, "decision", TODAY, "notes/a.md")
            self.assertEqual(draft.unused_notes([n], draft.load_history(path)), [])

    def test_record_rejects_unknown_pillar(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(draft.DraftError):
                draft.record(os.path.join(d, "history.json"), "nonsense", TODAY)

    def test_corrupt_history_raises_rather_than_silently_resetting(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.json")
            with open(path, "w") as f:
                f.write("{not json")
            with self.assertRaises(draft.DraftError):
                draft.load_history(path)

    def test_recorded_post_affects_the_next_selection(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "history.json")
            for _ in range(2):
                pillar, _ = draft.select(draft.load_history(path), TODAY, ALL_KEYS)
                draft.record(path, pillar["key"], TODAY)
            with open(path) as f:
                picked = [row["pillar"] for row in json.load(f)]
            # If history were ignored the rotation would return the same pillar
            # forever.
            self.assertEqual(picked, ["client-work", "decision"])


if __name__ == "__main__":
    unittest.main()
