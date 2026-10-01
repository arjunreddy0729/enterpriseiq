"""GET / - the public demo's front door. Registered only when DEMO_MODE is on.

Serves the static landing page, or redirects to the web UI when the
deployment mounts one (DEMO_UI_PATH).
"""

from __future__ import annotations

import html
from pathlib import Path
from string import Template

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.api.dependencies import SettingsDep

router = APIRouter(include_in_schema=False)

_TEMPLATE = Template((Path(__file__).resolve().parents[2] / "web" / "landing.html").read_text())


@router.get("/", response_class=HTMLResponse)
def landing(settings: SettingsDep) -> Response:
    if settings.demo_ui_path:
        return RedirectResponse(settings.demo_ui_path)
    password = settings.demo_user_password
    page = _TEMPLATE.substitute(
        password=html.escape(password.get_secret_value() if password else ""),
        repo_url=html.escape(settings.demo_repo_url, quote=True),
    )
    return HTMLResponse(page)
