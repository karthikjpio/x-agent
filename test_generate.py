#!/usr/bin/env python3
"""Tests for the generation step, none of which call a model.

The runner is injectable precisely so this file can cover the failure paths
that matter: a model that returns nothing, a command that is not installed, a
non-zero exit. Those are the cases that would otherwise only show up in
production, on a day with a real post to ship.

Run: python3 -m unittest test_generate -v
"""

import unittest

import generate


class TestUnwrap(unittest.TestCase):
    def test_plain_text_is_untouched_apart_from_whitespace(self):
        self.assertEqual(generate.unwrap("  a post.  \n"), "a post.")

    def test_a_fence_wrapping_the_whole_reply_is_stripped(self):
        self.assertEqual(generate.unwrap("```\na post.\n```"), "a post.")

    def test_a_language_tagged_fence_is_stripped(self):
        self.assertEqual(generate.unwrap("```text\na post.\n```"), "a post.")

    def test_an_inline_fence_is_left_alone(self):
        # A fence in the middle is part of the post, not packaging.
        text = "a post.\n\n```\ncode\n```\n\nmore."
        self.assertEqual(generate.unwrap(text), text)

    def test_a_preamble_is_not_silently_removed(self):
        # A model that ignored "return the post text and nothing else" is a real
        # problem. Tidying it here would hide it from the gate and from me.
        text = "Here is the post:\n\na post."
        self.assertEqual(generate.unwrap(text), text)


class TestGenerate(unittest.TestCase):
    def test_the_prompt_reaches_the_runner_unchanged(self):
        seen = []
        generate.generate("the prompt", lambda p: seen.append(p) or "a post.")
        self.assertEqual(seen, ["the prompt"])

    def test_the_draft_comes_back(self):
        self.assertEqual(generate.generate("p", lambda _: "a post."), "a post.")

    def test_an_empty_prompt_is_refused_before_calling_the_model(self):
        called = []
        for empty in ("", "   \n\n"):
            with self.assertRaises(generate.GenerateError):
                generate.generate(empty, lambda p: called.append(p) or "x")
        self.assertEqual(called, [])

    def test_an_empty_reply_is_an_error_not_an_empty_draft(self):
        for reply in ("", "   \n", "```\n\n```"):
            with self.assertRaises(generate.GenerateError) as cm:
                generate.generate("p", lambda _: reply)
            self.assertIn("returned nothing", str(cm.exception))

    def test_a_runner_failure_propagates(self):
        def boom(_):
            raise generate.GenerateError("claude exited 1: not logged in")
        with self.assertRaises(generate.GenerateError):
            generate.generate("p", boom)


class TestShellRunner(unittest.TestCase):
    def test_a_missing_command_says_so_clearly(self):
        with self.assertRaises(generate.GenerateError) as cm:
            generate.shell_runner("p", cmd=("definitely-not-installed-xyz",))
        self.assertIn("not on PATH", str(cm.exception))

    def test_a_real_command_round_trips_stdin_to_stdout(self):
        # `cat` stands in for the model: reads the prompt, writes it back.
        self.assertEqual(generate.shell_runner("hello", cmd=("cat",)), "hello")

    def test_a_non_zero_exit_is_reported_with_its_stderr(self):
        with self.assertRaises(generate.GenerateError) as cm:
            generate.shell_runner("p", cmd=("sh", "-c", "echo nope >&2; exit 3"))
        self.assertIn("exited 3", str(cm.exception))
        self.assertIn("nope", str(cm.exception))

    def test_a_hanging_command_times_out(self):
        with self.assertRaises(generate.GenerateError) as cm:
            generate.shell_runner("p", cmd=("sh", "-c", "sleep 5"), timeout=1)
        self.assertIn("nothing after", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
