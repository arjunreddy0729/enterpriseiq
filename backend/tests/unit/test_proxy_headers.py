"""Absolute URLs must use the scheme the visitor actually used.

Behind a TLS-terminating proxy the app receives plain http and learns the real
scheme only from X-Forwarded-Proto. If it ignores that header, every absolute
URL it generates - redirects above all - comes out as http://, and a browser
on an https page refuses to follow the downgrade.

The symptom is a blank page and no error anywhere. curl follows the redirect
without complaint, so the endpoint looks healthy from a terminal. That is why
this is a test rather than a note in the deployment docs.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import configure_app


def build(hops: int, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(get_settings(), "forwarded_proxy_hops", hops)
    app = FastAPI()

    @app.get("/thing/")
    def thing() -> dict[str, bool]:
        return {"ok": True}

    configure_app(app)
    return TestClient(app)


def test_redirect_keeps_https_behind_a_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build(1, monkeypatch)
    response = client.get("/thing", headers={"X-Forwarded-Proto": "https"}, follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"].startswith("https://"), response.headers["location"]


def test_header_is_ignored_when_no_proxy_is_declared(monkeypatch: pytest.MonkeyPatch) -> None:
    """With nothing in front of the app, anyone could send the header, so it
    must not be believed."""
    client = build(0, monkeypatch)
    response = client.get("/thing", headers={"X-Forwarded-Proto": "https"}, follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"].startswith("http://"), response.headers["location"]


def test_plain_http_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build(1, monkeypatch)
    response = client.get("/thing", follow_redirects=False)
    assert response.headers["location"].startswith("http://")
