#!/usr/bin/env python3
"""Tests for the draft quality gate.

Run: python3 -m unittest test_check -v
"""

import unittest

import check


def rules(findings, severity=None):
    return {f["rule"] for f in findings if severity is None or f["severity"] == severity}


MATERIAL = """
# Raw material for 2026-07-29

## `parivartane`
- **2026-07-07** `a1b2c3d` Redirect booking CTAs to WhatsApp DM
  > Scroll-to-form was losing 40% of mobile taps.
- **2026-07-07** `d4e5f6a` Add 3 preview variants
"""


class TestClean(unittest.TestCase):
    def test_clean_draft_passes(self):
        draft = "Moved a client's booking CTA from a scroll-to-form to a WhatsApp DM link. " \
                "Mobile taps were dying on the scroll. Ship the shortest path to the action."
        self.assertEqual(check.check(draft, MATERIAL), [])

    def test_supported_number_passes(self):
        draft = "The scroll-to-form was losing 40% of mobile taps. Moved the CTA to WhatsApp."
        self.assertEqual(rules(check.check(draft, MATERIAL), "fail"), set())


class TestVoiceRules(unittest.TestCase):
    def test_emoji_fails(self):
        self.assertIn("emoji", rules(check.check("Shipped it 🚀", MATERIAL)))

    def test_dingbat_emoji_fails(self):
        self.assertIn("emoji", rules(check.check("Shipped it ✨", MATERIAL)))

    def test_em_dash_fails(self):
        self.assertIn("em_dash", rules(check.check("Shipped it — finally.", MATERIAL)))

    def test_en_dash_fails(self):
        self.assertIn("em_dash", rules(check.check("Shipped it – finally.", MATERIAL)))

    def test_plain_hyphen_is_fine(self):
        self.assertNotIn("em_dash", rules(check.check("A scroll-to-form problem.", MATERIAL)))

    def test_hashtag_warns_but_does_not_block(self):
        found = check.check("Shipped a thing. #buildinpublic", MATERIAL)
        self.assertIn("hashtag", rules(found, "warn"))
        self.assertEqual(rules(found, "fail"), set())


class TestGateRules(unittest.TestCase):
    def test_over_length_fails(self):
        self.assertIn("length", rules(check.check("a" * 281, MATERIAL)))

    def test_exactly_at_limit_passes(self):
        self.assertNotIn("length", rules(check.check("a" * 280, MATERIAL)))

    def test_engagement_bait_fails(self):
        self.assertIn("engagement_bait",
                      rules(check.check("Moved the CTA. Thoughts?", MATERIAL)))

    def test_placeholder_fails(self):
        self.assertIn("placeholder", rules(check.check("Shipped TODO write this", MATERIAL)))

    def test_empty_draft_fails(self):
        self.assertIn("empty", rules(check.check("   ", MATERIAL)))


class TestNumberTracing(unittest.TestCase):
    def test_invented_number_fails(self):
        found = check.check("Cut response time by 87%.", MATERIAL)
        self.assertIn("unsupported_number", rules(found, "fail"))

    def test_comma_formatting_still_matches(self):
        found = check.check("Handled 1,200 requests.", "Handled 1200 requests.")
        self.assertEqual(rules(found, "fail"), set())

    def test_allow_whitelists_a_number(self):
        found = check.check("Cut it by 87%.", MATERIAL, allow=["87"])
        self.assertEqual(rules(found, "fail"), set())

    def test_no_material_warns_instead_of_failing(self):
        found = check.check("Cut response time by 87%.", None)
        self.assertIn("unverified_numbers", rules(found, "warn"))
        self.assertEqual(rules(found, "fail"), set())

    def test_draft_without_numbers_needs_no_material(self):
        self.assertEqual(check.check("Moved the CTA to WhatsApp.", None), [])


class TestThreads(unittest.TestCase):
    def test_each_post_length_checked_separately(self):
        draft = "a" * 200 + "\n---\n" + "b" * 200
        self.assertNotIn("length", rules(check.check(draft, MATERIAL, thread=True)))
        self.assertIn("length", rules(check.check(draft, MATERIAL, thread=False)))

    def test_number_introduced_in_post_one_supports_post_two(self):
        draft = "Lost 40% of mobile taps.\n---\nThat 40% came back after the change."
        self.assertEqual(rules(check.check(draft, MATERIAL, thread=True), "fail"), set())

    def test_finding_names_the_offending_post(self):
        draft = "fine\n---\n" + "b" * 300
        detail = [f for f in check.check(draft, MATERIAL, thread=True)
                  if f["rule"] == "length"][0]["detail"]
        self.assertTrue(detail.startswith("post 2:"), detail)


class TestReporting(unittest.TestCase):
    def test_passing_report_still_lists_human_checks(self):
        out = check.report(check.check("Moved the CTA to WhatsApp.", MATERIAL), False)
        self.assertIn("Automated checks pass.", out)
        self.assertIn("[ ]", out)

    def test_failing_report_does_not_claim_a_pass(self):
        out = check.report(check.check("Shipped it 🚀", MATERIAL), False)
        self.assertIn("blocking issue", out)
        self.assertNotIn("Automated checks pass.", out)


if __name__ == "__main__":
    unittest.main()
