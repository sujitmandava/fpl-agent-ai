"""HTTP client for the Fantasy Premier League public and authenticated APIs."""

from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api"


class FPLAuthError(RuntimeError):
    """Raised when FPL login fails (bad credentials or missing cookies)."""


class FPLClient:
    """Thin wrapper around the FPL REST API.

    Supports both public endpoints (bootstrap-static, fixtures) and
    authenticated endpoints (my-team, transfers) via session cookies.
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

    def login(self, email: str, password: str) -> None:
        """Authenticate with the FPL website to access manager-specific data.

        Raises ``FPLAuthError`` if the ``pl_profile`` cookie is not set
        after login (indicates bad credentials or a server-side change).
        """
        # Seed the session with any prerequisite cookies from the FPL site.
        self.session.get("https://fantasy.premierleague.com/", timeout=15)

        login_url = "https://users.premierleague.com/accounts/login/"
        payload = {
            "login": email,
            "password": password,
            "redirect_uri": "https://fantasy.premierleague.com/",
            "app": "plfpl-web",
        }
        login_headers = {
            "origin": "https://fantasy.premierleague.com",
            "referer": "https://fantasy.premierleague.com/my-team",
            "content-type": "application/x-www-form-urlencoded",
            "accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/webp,*/*;q=0.8"
            ),
        }
        resp = self.session.post(
            login_url, data=payload, headers=login_headers, timeout=15,
        )
        resp.raise_for_status()

        # The server returns 200 even on bad credentials; the only reliable
        # signal is the presence of the pl_profile cookie.
        cookie_names = {c.name for c in self.session.cookies}
        if "pl_profile" not in cookie_names:
            raise FPLAuthError(
                "Login failed — pl_profile cookie not set. "
                "Check your FPL_EMAIL and FPL_PASSWORD."
            )
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
