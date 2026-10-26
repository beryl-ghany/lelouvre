"""Test defaults — avoid blocking on Ollama during prepare/tailor."""
import os

os.environ.setdefault("LELOUVRE_TAILOR_OFFLINE", "1")
