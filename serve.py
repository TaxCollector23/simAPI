"""Run the Python API with the same-origin static dashboard mounted at `/`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DASHBOARD = ROOT / "dashboard"
sys.path.insert(0, str(ROOT))

from fastapi.staticfiles import StaticFiles  # noqa: E402

from api.server import app  # noqa: E402

# The API module's root route redirects to /docs. Remove that one route in this
# local dashboard launcher, then mount static files last so API routes keep
# precedence while `/` serves the dashboard.
app.router.routes = [
    route
    for route in app.router.routes
    if not (getattr(route, "path", None) == "/" and getattr(route, "name", None) == "root")
]
app.mount("/", StaticFiles(directory=str(DASHBOARD), html=True), name="dashboard")


if __name__ == "__main__":
    import uvicorn

    os.chdir(ROOT)
    uvicorn.run(
        app,
        host=os.environ.get("SIMAPI_HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        log_level="info",
    )
