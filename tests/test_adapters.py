import json
import unittest

from lelouvre.adapters.github_markdown import extract_github_markdown
from lelouvre.adapters.reddit_json import extract_reddit_json
from lelouvre.scout import SOURCE_MAP


class AdapterTests(unittest.TestCase):
    def test_github_markdown_extracts_verified_internship(self):
        line = (
            "| **[Acme Corp](https://acme.com)** | Software Engineering Intern - Summer 2027 | New York, NY | "
            "[Apply](https://boards.greenhouse.io/acme/jobs/999) | 1d |"
        )
        source = SOURCE_MAP["simplify2027"]
        records, seen = extract_github_markdown(source, line)
        self.assertEqual(seen, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["organization"], "Acme Corp")
        self.assertEqual(records[0]["kind"], "listing")
        self.assertIn("greenhouse.io", records[0]["url"])
        self.assertEqual(records[0]["evaluation"]["target"], "potential_match")

    def test_reddit_lead_without_apply_url(self):
        payload = {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": "abc123",
                            "title": "Software Engineering Intern — community question",
                            "selftext": "Python and Java experience.",
                            "url": "https://www.reddit.com/r/internships/comments/abc123/title/",
                            "is_self": True,
                            "permalink": "/r/internships/comments/abc123/title/",
                        },
                    }
                ]
            }
        }
        source = SOURCE_MAP["reddit_internships"]
        records, seen = extract_reddit_json(source, json.dumps(payload))
        self.assertEqual(seen, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["kind"], "lead")
        self.assertEqual(records[0]["evaluation"]["verification"], "unverified_lead")

    def test_reddit_post_with_greenhouse_link_becomes_listing(self):
        payload = {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "id": "def456",
                            "title": "Software Engineering Intern Summer 2027",
                            "selftext": "Apply: https://boards.greenhouse.io/acme/jobs/555",
                            "url": "https://www.reddit.com/r/internships/comments/def456/title/",
                            "is_self": True,
                            "permalink": "/r/internships/comments/def456/title/",
                        },
                    }
                ]
            }
        }
        source = SOURCE_MAP["reddit_internships"]
        records, _ = extract_reddit_json(source, json.dumps(payload))
        self.assertEqual(records[0]["kind"], "listing")
        self.assertIn("greenhouse.io", records[0]["url"])


if __name__ == "__main__":
    unittest.main()
