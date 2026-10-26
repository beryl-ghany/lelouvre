import unittest

from lelouvre.verify import best_apply_url, classify_apply_url, extract_urls


class VerifyTests(unittest.TestCase):
    def test_greenhouse_url_is_verified(self):
        url = "https://boards.greenhouse.io/cloudflare/jobs/123456"
        info = classify_apply_url(url)
        self.assertEqual(info["platform"], "greenhouse")
        self.assertEqual(info["confidence"], "verified_ats")

    def test_eu_greenhouse_url_is_verified(self):
        url = "https://boards.eu.greenhouse.io/acme/jobs/42"
        info = classify_apply_url(url)
        self.assertEqual(info["platform"], "greenhouse")
        self.assertEqual(info["external_job_id"], "42")

    def test_untrusted_host_is_rejected(self):
        self.assertIsNone(classify_apply_url("https://evil.example/jobs/1"))

    def test_best_apply_url_prefers_greenhouse_in_text(self):
        text = "Role details https://boards.greenhouse.io/acme/jobs/42 and https://example.com"
        url, info = best_apply_url(text)
        self.assertIn("greenhouse.io", url)
        self.assertEqual(info["platform"], "greenhouse")

    def test_extract_urls_strips_trailing_punctuation(self):
        urls = extract_urls("Apply at https://jobs.lever.co/acme/abc-123.")
        self.assertEqual(urls[0], "https://jobs.lever.co/acme/abc-123")


if __name__ == "__main__":
    unittest.main()
