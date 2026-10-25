"""Runtime settings."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Engine runtime settings.

    ``api_token`` is generated on first start and written to the data directory so
    the add-on UI or the integration can pair with the engine.
    """

    data_dir: Path
    api_token: str
    demo: bool = True
    require_auth: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.environ.get("DAEO_DATA_DIR", ".daeo-data")).expanduser()
        demo = _as_bool(os.environ.get("DAEO_DEMO", "1"))
        require_auth = _as_bool(
            os.environ.get("DAEO_REQUIRE_AUTH", "0" if demo else "1")
        )
        token = os.environ.get("DAEO_API_TOKEN", "").strip()
        token_file = data_dir / "api_token"
        if not token and token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()
        if not token:
            token = secrets.token_urlsafe(32)
        return cls(
            data_dir=data_dir,
            api_token=token,
            demo=demo,
            require_auth=require_auth,
        )
