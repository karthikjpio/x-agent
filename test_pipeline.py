import datetime as dt
import json
import os
import tempfile
import unittest

import pipeline


TODAY = dt.date(2026, 7, 29)


def write_note(folder, pillar="method", body="A 5 step method worked.", publishable=False):
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "2026-07-29-%s.md" % pillar)
    with open(path, "w") as f:
        f.write(
            "---\npillar: %s\nsource: Karthik in Buzz event abc\n"
            "source_kind: private\npublishable: %s\ndate: 2026-07-29\n---\n\n%s\n"
            % (pillar, "yes" if publishable else "no", body)
        )
    return path


def no_commits(today, raw_dir):
    os.makedirs(raw_dir, exist_ok=True)
    path = os.path.join(raw_dir, "GATHER_%s.md" % today.isoformat())
    text = "## No public commits in this window\n"
    with open(path, "w") as f:
        f.write(text)
    return path, text


def commits(today, raw_dir):
    os.makedirs(raw_dir, exist_ok=True)
    path = os.path.join(raw_dir, "GATHER_%s.md" % today.isoformat())
    text = "## repo\n\n- 2026-07-29 abc1234 Added a source gate\n"
    with open(path, "w") as f:
        f.write(text)
    return path, text


class PipelineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = os.path.join(self.tmp.name, "state")
        self.notes = os.path.join(self.tmp.name, "notes")
        self.raw = os.path.join(self.tmp.name, "raw")
        self.deny = os.path.join(self.tmp.name, "denylist")

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, runner, gatherer=no_commits):
        return pipeline.start(
            state_dir=self.state,
            notes_dir=self.notes,
            raw_dir=self.raw,
            denylist_path=self.deny,
            today=TODAY,
            runner=runner,
            gatherer=gatherer,
        )


class TestRun(PipelineCase):
    def test_note_backed_happy_path_uses_the_note_for_number_checks(self):
        write_note(self.notes)
        row = self.start(lambda prompt: "The 5 step method caught the bad draft.")
        self.assertEqual("awaiting_review", row["status"])
        card = pipeline.delivery_card(row)
        self.assertEqual("The 5 step method caught the bad draft.", card["draft"])
        self.assertTrue(card["gate"]["pass"])

    def test_duplicate_daily_trigger_returns_the_same_run(self):
        write_note(self.notes)
        calls = []

        def runner(prompt):
            calls.append(prompt)
            return "The 5 step method caught the bad draft."

        first = self.start(runner)
        second = self.start(runner)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(1, len(calls))

    def test_commit_backed_build_pauses_for_interview_without_model_call(self):
        calls = []
        row = self.start(lambda prompt: calls.append(prompt), gatherer=commits)
        self.assertEqual("needs_interview", row["status"])
        self.assertEqual([], calls)
        self.assertEqual(5, len(row["review"]["questions"]))

    def test_gate_failure_is_retried_without_widening_source(self):
        write_note(self.notes)
        replies = iter([
            "This unsupported result was 99 times faster.",
            "The 5 step method caught the bad draft.",
        ])
        row = self.start(lambda prompt: next(replies))
        self.assertEqual("awaiting_review", row["status"])
        self.assertEqual(2, row["attempts"])

    def test_nothing_eligible_is_a_visible_skip(self):
        row = self.start(lambda prompt: self.fail("model must not run"))
        self.assertEqual("skipped", row["status"])
        self.assertIn("no source", row["reason"])


class TestReviewLifecycle(PipelineCase):
    def make_ready(self):
        write_note(self.notes)
        return self.start(lambda prompt: "The 5 step method caught the bad draft.")

    def test_approval_does_not_spend_the_note_publication_does(self):
        row = self.make_ready()
        approved = pipeline.transition(self.state, row["id"], "approve")
        self.assertEqual("approved", approved["status"])
        self.assertFalse(os.path.exists(os.path.join(self.state, "history.json")))

        published = pipeline.transition(
            self.state, row["id"], "published", post_url="https://x.com/test/status/1")
        self.assertEqual("published", published["status"])
        with open(os.path.join(self.state, "history.json")) as f:
            history = json.load(f)
        self.assertEqual(1, len(history))
        again = pipeline.transition(
            self.state, row["id"], "published", post_url="https://x.com/test/status/1")
        self.assertEqual("published", again["status"])
        with open(os.path.join(self.state, "history.json")) as f:
            self.assertEqual(1, len(json.load(f)))

    def test_rejection_keeps_the_source_unspent(self):
        row = self.make_ready()
        rejected = pipeline.transition(
            self.state, row["id"], "reject", feedback="Make the opening concrete.")
        self.assertEqual("rejected", rejected["status"])
        self.assertFalse(os.path.exists(os.path.join(self.state, "history.json")))

    def test_delivery_event_is_recorded_once(self):
        row = self.make_ready()
        delivered = pipeline.transition(
            self.state, row["id"], "delivered", delivery_event="event-one")
        self.assertEqual("event-one", delivered["delivery_event_id"])
        again = pipeline.transition(
            self.state, row["id"], "delivered", delivery_event="event-one")
        self.assertEqual("event-one", again["delivery_event_id"])
        with self.assertRaises(pipeline.PipelineError):
            pipeline.transition(
                self.state, row["id"], "delivered", delivery_event="event-two")

    def test_publication_rejects_a_non_x_url(self):
        row = self.make_ready()
        pipeline.transition(self.state, row["id"], "approve")
        with self.assertRaises(pipeline.PipelineError):
            pipeline.transition(
                self.state, row["id"], "published",
                post_url="https://example.com/status/1")

    def test_interview_answer_requires_explicit_publishability(self):
        row = self.start(lambda prompt: self.fail("model must not run"), gatherer=commits)
        with self.assertRaises(pipeline.PipelineError):
            pipeline.transition(
                self.state, row["id"], "answer", answer="A safe answer.",
                source="Buzz event xyz", notes_dir=self.notes)
        captured = pipeline.transition(
            self.state, row["id"], "answer", answer="A safe answer.",
            source="Buzz event xyz", publishable=True, notes_dir=self.notes)
        self.assertEqual("interview_answered", captured["status"])
        self.assertTrue(os.path.exists(captured["captured_note"]))

    def test_revision_uses_feedback_and_returns_to_review(self):
        row = self.make_ready()
        rejected = pipeline.transition(
            self.state, row["id"], "reject", feedback="Start with the failure.")
        revised = pipeline.transition(
            self.state, row["id"], "revise",
            runner=lambda prompt: "The 5 step method failed once, then caught the draft.")
        self.assertEqual("awaiting_review", revised["status"])
        self.assertGreaterEqual(revised["version"], 2)


if __name__ == "__main__":
    unittest.main()
