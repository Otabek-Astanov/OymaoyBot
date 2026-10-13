import re
from pathlib import Path


def test_example_environment_has_no_botfather_token():
    text = (Path(__file__).resolve().parents[1] / ".env.example").read_text()
    contains_token = bool(re.search(r"\b\d{5,}:[A-Za-z0-9_-]{30,}\b", text))
    assert contains_token is False, "Example contains a Telegram token"
