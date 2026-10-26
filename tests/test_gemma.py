import json
import unittest

from lelouvre.gemma import GemmaClient


class GemmaClientTests(unittest.TestCase):
    def test_chat_json_uses_transport(self):
        captured = {}

        def transport(url, payload, timeout=120):
            captured["url"] = url
            captured["model"] = payload["model"]
            return {"message": {"content": json.dumps({"bullets": [{"text": "a", "source_id": "x"}]})}}

        client = GemmaClient(model="gemma3:4b", transport=transport)
        out = client.chat_json([{"role": "user", "content": "hi"}], {"type": "object"})
        self.assertIn("/api/chat", captured["url"])
        self.assertEqual(captured["model"], "gemma3:4b")
        self.assertIn("bullets", out)


if __name__ == "__main__":
    unittest.main()
