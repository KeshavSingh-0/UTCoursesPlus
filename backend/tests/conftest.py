import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Tests never read or write the real settings file, and never pick up a real API key from the environment."""
    from utcoursesplus import settings

    monkeypatch.setattr(settings, "PATH", tmp_path / "settings.json")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("UTCP_MODEL", raising=False)
