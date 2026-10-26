import unittest

from lelouvre.policy import auto_execute_blockers


class PolicyTests(unittest.TestCase):
    def test_blocks_unconfirmed_season_and_unlikely_eligibility(self):
        evaluation = {"target": "needs_review", "season": "unknown", "verification": "verified_ats"}
        packet = {"analysis": {"eligibility": "unlikely", "review_flags": ["Clearance required"]}}
        blockers = auto_execute_blockers(packet, evaluation)
        self.assertTrue(any("season" in b.lower() for b in blockers))
        self.assertTrue(any("unlikely" in b.lower() for b in blockers))

    def test_allows_clean_confirmed_match(self):
        evaluation = {"target": "potential_match", "season": "confirmed", "verification": "verified_ats"}
        packet = {"analysis": {"eligibility": "likely", "review_flags": []}}
        self.assertEqual(auto_execute_blockers(packet, evaluation), [])


if __name__ == "__main__":
    unittest.main()
