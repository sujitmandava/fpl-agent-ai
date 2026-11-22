"""Tests for the refresh-token login (no network)."""

import json
import os
from unittest.mock import MagicMock

import pytest

from fpl_agent.data_ingest import FPLClient
from fpl_agent.data_ingest.auth import (
    AUTH_HEADER, CLIENT_ID, FPLAuthError, TokenStore, parse_token, refresh_access_token,
)


def _resp(ok=True, body=None, status=200):
    r = MagicMock(ok=ok, status_code=status)
    r.json.return_value = body or {}
    return r


def test_parse_raw_and_json():
    assert parse_token(" abc ") == ("abc", None)
    pasted = json.dumps({"id_token": "x", "refresh_token": "rt", "client_id": "cid"})
    assert parse_token(f"'{pasted}'") == ("rt", "cid")
    with pytest.raises(FPLAuthError):
        parse_token('{"access_token": "only"}')


def test_refresh_saves_rotated_token(tmp_path):
    store = TokenStore(tmp_path / "auth.json")
    session = MagicMock()
    session.post.return_value = _resp(body={"access_token": "AT", "refresh_token": "RT2"})
    assert refresh_access_token(session, "RT1", store) == "AT"
    form = session.post.call_args.kwargs["data"]
    assert form == {"grant_type": "refresh_token", "client_id": CLIENT_ID, "refresh_token": "RT1"}
    saved = store.load()
    assert saved["refresh_token"] == "RT2" and saved["seed"] == "RT1"
    assert oct(os.stat(store.path).st_mode & 0o777) == "0o600"

    # Next run: the .env value is spent, so the saved token is used instead.
    session.post.reset_mock()
    session.post.return_value = _resp(body={"access_token": "AT3", "refresh_token": "RT3"})
    refresh_access_token(session, "RT1", store)
    assert session.post.call_count == 1
    assert session.post.call_args.kwargs["data"]["refresh_token"] == "RT2"


def test_newly_pasted_token_wins(tmp_path):
    store = TokenStore(tmp_path / "auth.json")
    store.save({"refresh_token": "OLD", "client_id": CLIENT_ID, "seed": "RT1"})
    session = MagicMock()
    session.post.return_value = _resp(body={"access_token": "AT", "refresh_token": "N2"})
    refresh_access_token(session, "NEW", store)
    assert session.post.call_args.kwargs["data"]["refresh_token"] == "NEW"


def test_falls_back_then_fails_clearly(tmp_path):
    store = TokenStore(tmp_path / "auth.json")
    store.save({"refresh_token": "OLD", "client_id": CLIENT_ID, "seed": "RT1"})
    session = MagicMock()
    session.post.return_value = _resp(ok=False, status=400, body={"error": "invalid_grant"})
    with pytest.raises(FPLAuthError, match="invalid_grant"):
        refresh_access_token(session, "NEW", store)
    assert session.post.call_count == 2
    with pytest.raises(FPLAuthError, match="No FPL_REFRESH_TOKEN"):
        refresh_access_token(session, None, TokenStore(tmp_path / "none.json"))


def test_client_login_sets_bearer_header(tmp_path):
    session = MagicMock()
    session.headers = {}
    session.post.return_value = _resp(body={"access_token": "AT", "refresh_token": "R2"})
    client = FPLClient(session=session)
    client.login("R1", TokenStore(tmp_path / "auth.json"))
    assert client.authenticated
    assert session.headers[AUTH_HEADER] == "Bearer AT"
