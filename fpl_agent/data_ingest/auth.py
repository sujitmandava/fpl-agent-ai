"""FPL login via the Premier League's OAuth service (account.premierleague.com).

The old ``users.premierleague.com`` email/password login no longer exists, and
the new sign-in page rejects scripted logins. Instead you sign in once in a
browser, copy the *refresh token* the FPL site stores, and this module trades
it for short-lived access tokens.

Two details matter:

* The refresh token **rotates**: every refresh returns a new one and the old
  one stops working. The newest is saved to ``FPL_AUTH_FILE`` (default
  ``.fpl_auth.json``, readable only by you), so ``FPL_REFRESH_TOKEN`` in
  ``.env`` is needed only once, or again after it expires (~30 days unused).
* Using the token may sign your browser out of FPL; just log in there again.

Where to find the token: on fantasy.premierleague.com (logged in), open
DevTools → Application → Local Storage → https://fantasy.premierleague.com,
pick the key starting ``oidc.user:``, and copy its value. Either the whole
JSON value or just its ``refresh_token`` field works.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

TOKEN_URL = "https://account.premierleague.com/as/token"
# Public client id of the FPL web app (no secret); it is also the last part of
# the ``oidc.user:`` localStorage key.
CLIENT_ID = "bfcbaf69-aade-4c1b-8f00-c1cb8a193030"
AUTH_HEADER = "X-API-Authorization"


class FPLAuthError(RuntimeError):
    """Raised when no usable FPL token is available."""


def parse_token(value: str) -> tuple[str, str | None]:
    """Return (refresh_token, client_id) from a raw token or the pasted JSON value."""
    value = value.strip().strip("'\"")
    if value.startswith("{"):
        try:
            data = json.loads(value)
        except json.JSONDecodeError as exc:
            raise FPLAuthError("FPL_REFRESH_TOKEN looks like JSON but doesn't parse.") from exc
        token = data.get("refresh_token")
        if not token:
            raise FPLAuthError("The pasted JSON has no refresh_token field.")
        return token, data.get("client_id")
    return value, None


class TokenStore:
    """The latest refresh token, persisted because each refresh rotates it."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.environ.get("FPL_AUTH_FILE", ".fpl_auth.json"))

    def load(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def save(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)


def candidate_tokens(env_value: str | None, saved: dict) -> list[tuple[str, str, str]]:
    """(refresh_token, client_id, seed) to try, newest first.

    A value in ``.env`` that differs from the one that seeded the saved token
    was pasted since, so it is tried first; otherwise the saved (rotated)
    token is the current one and the ``.env`` copy is already spent.
    """
    out: list[tuple[str, str, str]] = []
    env_tok = parse_token(env_value) if env_value and env_value.strip() else None
    seed = env_value.strip() if env_tok else ""
    if env_tok and seed != saved.get("seed"):
        out.append((env_tok[0], env_tok[1] or CLIENT_ID, seed))
    if saved.get("refresh_token"):
        out.append((saved["refresh_token"], saved.get("client_id") or CLIENT_ID,
                    saved.get("seed", "")))
    return out


def refresh_access_token(session: requests.Session, env_value: str | None,
                         store: TokenStore | None = None) -> str:
    """Exchange the newest refresh token for an access token; save the rotated one."""
    store = store or TokenStore()
    candidates = candidate_tokens(env_value, store.load())
    if not candidates:
        raise FPLAuthError("No FPL_REFRESH_TOKEN set.")
    errors = []
    for token, client_id, seed in candidates:
        resp = session.post(TOKEN_URL, data={
            "grant_type": "refresh_token", "client_id": client_id, "refresh_token": token,
        }, headers={"Accept": "application/json"}, timeout=15)
        if resp.ok:
            body = resp.json()
            store.save({"refresh_token": body.get("refresh_token", token),
                        "client_id": client_id, "seed": seed})
            logger.info("FPL access token refreshed (expires in %ss).", body.get("expires_in"))
            return body["access_token"]
        try:
            err = resp.json().get("error_description") or resp.json().get("error")
        except ValueError:
            err = resp.text[:120]
        errors.append(f"{resp.status_code} {err}")
    raise FPLAuthError(
        "FPL token was rejected (" + "; ".join(errors) + "). It has expired or was already "
        "used: copy a fresh one from your browser into FPL_REFRESH_TOKEN.")
