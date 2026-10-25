"""Run the engine with uvicorn."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "daeo.api.app:create_app",
        factory=True,
        host=os.environ.get("DAEO_HOST", "0.0.0.0"),  # noqa: S104 - container service
        port=int(os.environ.get("DAEO_PORT", "8099")),
        log_level=os.environ.get("DAEO_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
