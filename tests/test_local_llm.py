import json
import unittest

from lelouvre.local_llm import OllamaProvider


class OllamaProviderTests(unittest.TestCase):
    def test_structured_local_analysis_preserves_discovery_basis(self):
        captured = {}
        result = {"role_category":"cloud_security", "season":"summer_2027",
                  "location_status":"us_outside_south_carolina", "eligibility":"needs_review",
                  "summary":"Cloud security internship.", "requirements":[], "review_flags":["authorization wording"],
                  "evidence":["Summer 2027 — Seattle"]}
        def transport(payload):
            captured.update(payload); return {"message":{"content":json.dumps(result)}}
        analysis = OllamaProvider(transport=transport).analyze({"title":"Cloud Security Intern", "description":"Summer 2027 — Seattle"})
        self.assertEqual(analysis["provider"], "gemma")
        self.assertIn("resume skill overlap must not gate", captured["messages"][1]["content"])
        self.assertEqual(captured["format"]["additionalProperties"], False)

    def test_deterministic_location_check_corrects_model_error(self):
        wrong = {"role_category":"cloud_security", "season":"summer_2027", "location_status":"south_carolina",
                 "eligibility":"unlikely", "summary":"", "requirements":[], "review_flags":[], "evidence":[]}
        provider = OllamaProvider(transport=lambda _:{"message":{"content":json.dumps(wrong)}})
        result = provider.analyze({"title":"Cloud Security Intern", "location":"Seattle, WA", "description":"Summer 2027"})
        self.assertEqual(result["location_status"], "us_outside_south_carolina")
        self.assertTrue(any("corrected" in flag for flag in result["review_flags"]))


if __name__ == "__main__": unittest.main()
