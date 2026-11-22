"""HTTP client for the Fantasy Premier League public and authenticated APIs."""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .auth import AUTH_HEADER, FPLAuthError, TokenStore, refresh_access_token  # noqa: F401

logger = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api"


class FPLClient:
    """Thin wrapper around the FPL REST API.

    Supports both public endpoints (bootstrap-static, fixtures) and
    authenticated endpoints (my-team) via an OAuth bearer token.
    """

    _BROWSER_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )

    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self._BROWSER_UA})
        # Retry transient failures (FPL returns 5xx/429 around deadlines).
        retry = Retry(
            total=4, backoff_factor=1.0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        if hasattr(self.session, "mount"):
            adapter = HTTPAdapter(max_retries=retry, pool_maxsize=16)
            self.session.mount("https://", adapter)
        self.authenticated = False

    # -- Authentication -------------------------------------------------------

    def login(self, refresh_token: str | None, store: TokenStore | None = None) -> None:
        """Authenticate with an FPL refresh token (see ``auth``).

        Raises ``FPLAuthError`` when no token works.
        """
        access = refresh_access_token(self.session, refresh_token, store)
        self.session.headers[AUTH_HEADER] = f"Bearer {access}"
        self.authenticated = True
        logger.info("Authenticated with FPL successfully.")

    # -- Public endpoints -----------------------------------------------------

    def get_bootstrap(self) -> dict[str, Any]:
        """Return the full bootstrap-static payload (players, teams, events)."""
        return self._get("/bootstrap-static/")

    def get_fixtures(self) -> list[dict[str, Any]]:
        """Return all fixtures for the current season."""
        return self._get("/fixtures/")

    def get_player_summary(self, player_id: int) -> dict[str, Any]:
        """Return per-match history and upcoming fixtures for *player_id*."""
        return self._get(f"/element-summary/{player_id}/")

    def get_gameweek_live(self, gameweek: int) -> dict[str, Any]:
        """Return live scoring data for *gameweek*."""
        return self._get(f"/event/{gameweek}/live/")

    # -- Authenticated endpoints ----------------------------------------------

    def get_my_team(self, manager_id: int) -> dict[str, Any]:
        """Return the current squad for *manager_id* (requires login)."""
        return self._get(f"/my-team/{manager_id}/")

    def get_entry(self, manager_id: int) -> dict[str, Any]:
        """Return public profile for *manager_id* (team name, rank, leagues)."""
        return self._get(f"/entry/{manager_id}/")

    def get_manager_history(self, manager_id: int) -> dict[str, Any]:
        """Return overall season history for *manager_id*."""
        return self._get(f"/entry/{manager_id}/history/")

    def get_manager_picks(self, manager_id: int, gameweek: int) -> dict[str, Any]:
        """Return picks for *manager_id* in *gameweek*."""
        return self._get(f"/entry/{manager_id}/event/{gameweek}/picks/")

    def get_manager_transfers(self, manager_id: int) -> list[dict[str, Any]]:
        """Return all transfers made by *manager_id* this season."""
        return self._get(f"/entry/{manager_id}/transfers/")

    # -- Internal helpers -----------------------------------------------------

    def _get(self, path: str) -> Any:
        url = f"{BASE_URL}{path}"
        logger.debug("GET %s", url)
        resp = self.session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.json()
