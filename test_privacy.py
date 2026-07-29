import os
import tempfile
import unittest

import privacy


class TestPrivacy(unittest.TestCase):
    def test_plain_text_passes(self):
        self.assertEqual([], privacy.findings("Built a small parser."))

    def test_common_secrets_are_blocked(self):
        cases = [
            "gho_" + "a" * 30,
            "sk-" + "a" * 30,
            "nsec1" + "a" * 50,
            "-----BEGIN PRIVATE KEY-----",
            "+49 123 456 7890",
        ]
        for text in cases:
            with self.subTest(text=text[:8]):
                self.assertTrue(privacy.findings(text))

    def test_private_terms_load_without_being_named_in_public_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "deny.txt")
            with open(path, "w") as f:
                f.write("# comment\nSecret Client Alpha\n")
            terms = privacy.load_denylist(path)
            self.assertEqual(["Secret Client Alpha"], terms)
            with self.assertRaises(privacy.PrivacyError):
                privacy.require_safe("work for secret client alpha", terms)
