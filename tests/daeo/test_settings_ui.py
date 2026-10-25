"""Settings UI completeness tests."""

from __future__ import annotations

import re
from pathlib import Path

from daeo.config.models import Config

SETTINGS_JS = (
    Path(__file__).resolve().parents[2] / "src" / "daeo" / "web" / "settings.js"
)


def test_every_config_section_is_rendered_in_settings() -> None:
    """Every top-level config model field must have a Settings card."""
    source = SETTINGS_JS.read_text(encoding="utf-8")
    match = re.search(r"const TOP_LEVEL = \[(.*?)\];", source, re.DOTALL)
    assert match is not None, "settings.js TOP_LEVEL not found"

    rendered = set(re.findall(r'\[\s*"([^"]+)"\s*,', match.group(1)))
    required = set(Config.model_fields) - {"schema_version"}
    missing = required - rendered

    assert not missing, (
        "Settings UI is missing top-level config sections: "
        f"{sorted(missing)}"
    )
