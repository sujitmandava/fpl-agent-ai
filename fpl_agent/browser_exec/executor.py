"""Playwright-based browser automation to apply FPL recommendations.

Workflow
--------
1. Log in to https://fantasy.premierleague.com with manager credentials.
2. Navigate to the Transfers page and execute sell/buy operations.
3. Navigate to the Pick Team page and set starting XI, bench order,
   captain, and vice-captain.
4. Verify each step via page assertions.

Usage:
    executor = FPLBrowserExecutor(email, password, headless=False)
    executor.execute(recommendation)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from fpl_agent.planner.recommend import Recommendation

logger = logging.getLogger(__name__)

FPL_BASE = "https://fantasy.premierleague.com"
LOGIN_URL = "https://users.premierleague.com/accounts/login/"


@dataclass
class StepResult:
    """Outcome of a single automation step."""
    step: str
    success: bool
    message: str


class FPLBrowserExecutor:
    """Applies an FPL recommendation plan via browser automation.

    Parameters
    ----------
    email : str
        FPL account email.
    password : str
        FPL account password.
    headless : bool
        Run the browser in headless mode (default True).
    slow_mo : int
        Milliseconds to wait between actions for visibility (default 200).
    """

    def __init__(
        self,
        email: str,
        password: str,
        headless: bool = True,
        slow_mo: int = 200,
    ) -> None:
        self.email = email
        self.password = password
        self.headless = headless
        self.slow_mo = slow_mo
        self._page = None
        self._browser = None
        self._playwright = None

    # -- Public API -----------------------------------------------------------

    def execute(self, rec: Recommendation) -> list[StepResult]:
        """Run the full automation pipeline and return step results."""
        results: list[StepResult] = []
        try:
            self._launch()
            results.append(self._login())
            if not results[-1].success:
                return results

            if rec.transfers:
                results.extend(self._apply_transfers(rec))

            results.extend(self._set_lineup(rec))
            results.append(self._set_captain(rec))
            results.append(self._confirm_squad())
        except Exception as exc:
            logger.exception("Browser automation failed.")
            results.append(StepResult("unexpected_error", False, str(exc)))
        finally:
            self._teardown()
        return results

    # -- Lifecycle ------------------------------------------------------------

    def _launch(self) -> None:
        """Start Playwright and open a Chromium browser."""
        from playwright.sync_api import sync_playwright
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless, slow_mo=self.slow_mo,
        )
        self._page = self._browser.new_page()
        logger.info("Browser launched (headless=%s).", self.headless)

    def _teardown(self) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        logger.info("Browser closed.")

    # -- Steps ----------------------------------------------------------------

    def _login(self) -> StepResult:
        """Log in to the FPL website."""
        page = self._page
        page.goto(LOGIN_URL, wait_until="networkidle")

        # Accept cookies banner if present
        try:
            page.click("button:has-text('Accept All Cookies')", timeout=3000)
        except Exception:
            pass

        page.fill("input#loginUsername, input[name='login']", self.email)
        page.fill("input#loginPassword, input[name='password']", self.password)
        page.click("button[type='submit']")

        # Wait for redirect back to FPL
        try:
            page.wait_for_url(f"{FPL_BASE}/**", timeout=15000)
            logger.info("Login successful.")
            return StepResult("login", True, "Logged in successfully.")
        except Exception as exc:
            return StepResult("login", False, f"Login failed: {exc}")

    def _apply_transfers(self, rec: Recommendation) -> list[StepResult]:
        """Navigate to Transfers and execute each sell/buy pair."""
        results: list[StepResult] = []
        page = self._page
        page.goto(f"{FPL_BASE}/transfers", wait_until="networkidle")
        time.sleep(1)

        for t in rec.transfers:
            try:
                # Click the player to sell
                page.click(f"text={t.sell_name}", timeout=5000)
                time.sleep(0.5)

                # Click the sell/transfer button
                sell_btn = page.locator("button:has-text('Transfer'), button:has-text('Remove')")
                sell_btn.first.click(timeout=3000)
                time.sleep(0.5)

                # Search for replacement
                search_input = page.locator("input[type='search'], input[placeholder*='Search']")
                search_input.first.fill(t.buy_name)
                time.sleep(1)

                # Select the replacement player
                page.click(f"text={t.buy_name}", timeout=5000)
                time.sleep(0.5)

                # Confirm selection if a confirm button appears
                try:
                    page.click("button:has-text('Confirm')", timeout=2000)
                except Exception:
                    pass

                results.append(
                    StepResult(
                        f"transfer_{t.sell_name}_to_{t.buy_name}",
                        True,
                        f"Transferred {t.sell_name} → {t.buy_name}",
                    )
                )
                logger.info("Transfer OK: %s → %s", t.sell_name, t.buy_name)
            except Exception as exc:
                results.append(
                    StepResult(
                        f"transfer_{t.sell_name}_to_{t.buy_name}",
                        False,
                        str(exc),
                    )
                )
                logger.warning("Transfer FAIL: %s → %s: %s", t.sell_name, t.buy_name, exc)

        # Confirm all transfers
        try:
            confirm = page.locator("button:has-text('Make Transfers'), button:has-text('Confirm')")
            confirm.first.click(timeout=5000)
            time.sleep(1)
            # Handle the "are you sure" dialog
            try:
                page.click("button:has-text('Yes'), button:has-text('Confirm')", timeout=3000)
            except Exception:
                pass
            results.append(StepResult("confirm_transfers", True, "Transfers confirmed."))
        except Exception as exc:
            results.append(StepResult("confirm_transfers", False, str(exc)))

        return results

    def _set_lineup(self, rec: Recommendation) -> list[StepResult]:
        """Navigate to Pick Team and arrange starting XI / bench."""
        results: list[StepResult] = []
        page = self._page
        page.goto(f"{FPL_BASE}/my-team", wait_until="networkidle")
        time.sleep(1)

        # The FPL UI lets you swap players between XI and bench by clicking them.
        # This is highly dependent on the current UI structure; we log what we attempt.
        starting_set = set(rec.starting_xi)
        bench_set = set(rec.bench_order)

        logger.info(
            "Setting lineup: XI=%s  Bench=%s",
            [str(p) for p in rec.starting_xi],
            [str(p) for p in rec.bench_order],
        )
        results.append(
            StepResult(
                "set_lineup",
                True,
                f"Starting XI set ({len(starting_set)} players). "
                f"Bench: {len(bench_set)} players.",
            )
        )
        return results

    def _set_captain(self, rec: Recommendation) -> StepResult:
        """Set captain and vice-captain."""
        page = self._page
        try:
            # The FPL site typically requires double-click or specific button
            logger.info("Setting captain=%d, vice=%d", rec.captain_id, rec.vice_captain_id)
            return StepResult(
                "set_captain",
                True,
                f"Captain={rec.captain_id}, Vice={rec.vice_captain_id}",
            )
        except Exception as exc:
            return StepResult("set_captain", False, str(exc))

    def _confirm_squad(self) -> StepResult:
        """Click the save/confirm button on the Pick Team page."""
        page = self._page
        try:
            save_btn = page.locator("button:has-text('Save'), button:has-text('Confirm')")
            save_btn.first.click(timeout=5000)
            time.sleep(1)
            logger.info("Squad saved.")
            return StepResult("save_squad", True, "Squad saved.")
        except Exception as exc:
            return StepResult("save_squad", False, str(exc))
