"""
E*Trade Broker
==============
Handles OAuth authentication and order placement for E*Trade.
Supports paper trading (sandbox) and live trading modes.

E*Trade API docs: https://developer.etrade.com/getting-started

IMPORTANT: E*Trade uses OAuth 1.0a with a browser-based token flow.
The first run will open a browser for you to authorize the app.
The token is then saved locally and reused until it expires.
"""

import os
import sys
import time
import json
import logging
import webbrowser
from pathlib import Path
from datetime import datetime

import requests
from requests_oauthlib import OAuth1Session

from config.settings import (
    PAPER_TRADING,
    ETRADE_CONSUMER_KEY, ETRADE_CONSUMER_SECRET,
    ETRADE_SANDBOX_KEY, ETRADE_SANDBOX_SECRET,
    TRADE_AMOUNT_USD
)

logger = logging.getLogger("trading_agent")

# E*Trade base URLs
LIVE_BASE    = "https://api.etrade.com"
SANDBOX_BASE = "https://apisb.etrade.com"
TOKEN_FILE   = "config/.etrade_token.json"

# Headless-auth bookkeeping. When the agent runs under nohup/launchd (no TTY),
# it can't prompt for the OAuth verifier. Instead it writes a pending-auth
# status file with the URL the user needs to visit, and polls for a verifier
# file that the user creates with: `echo CODE > config/.etrade_verifier`.
AUTH_PENDING_FILE = "config/.etrade_auth_pending"
AUTH_VERIFIER_FILE = "config/.etrade_verifier"
AUTH_POLL_SEC = 5                # how often to look for the verifier file
AUTH_TIMEOUT_SEC = 30 * 60       # give up after 30 minutes


class ETradeClient:
    def __init__(self):
        self.paper = PAPER_TRADING
        self.base  = SANDBOX_BASE if self.paper else LIVE_BASE
        self.key    = ETRADE_SANDBOX_KEY    if self.paper else ETRADE_CONSUMER_KEY
        self.secret = ETRADE_SANDBOX_SECRET if self.paper else ETRADE_CONSUMER_SECRET
        self.session: OAuth1Session | None = None
        self.account_id: str | None = None

        mode = "PAPER (Sandbox)" if self.paper else "*** LIVE TRADING ***"
        logger.info(f"ETradeClient initialized — Mode: {mode}")

    # ------------------------------------------------------------------
    # Authentication (OAuth 1.0a — browser flow)
    # ------------------------------------------------------------------

    def _oauth_base(self) -> str:
        """OAuth token endpoints: sandbox uses apisb, live uses api."""
        return SANDBOX_BASE if self.paper else LIVE_BASE

    def authenticate(self):
        """
        Full OAuth 1.0a flow. On first run, opens browser for authorization.
        Saves token to disk for reuse.
        """
        if self._load_token():
            logger.info("Loaded existing E*Trade token")
            return

        logger.info("Starting E*Trade OAuth flow...")

        oauth_base = self._oauth_base()
        request_token_url = f"{oauth_base}/oauth/request_token"
        oauth = OAuth1Session(self.key, client_secret=self.secret,
                              callback_uri="oob")
        fetch_response = oauth.fetch_request_token(request_token_url)
        resource_owner_key    = fetch_response.get("oauth_token")
        resource_owner_secret = fetch_response.get("oauth_token_secret")

        # Authorization page is always on us.etrade.com (even for sandbox keys).
        auth_url = f"https://us.etrade.com/e/t/etws/authorize"
        auth_url += f"?key={self.key}&token={resource_owner_key}"
        print(f"\n{'='*60}")
        print(f"Opening browser to authorize E*Trade access...")
        print(f"If browser doesn't open, visit:\n{auth_url}")
        print(f"{'='*60}\n")
        webbrowser.open(auth_url)

        # Step 3: User pastes verifier code (TTY-safe — works under nohup too)
        verifier = self._read_verifier(auth_url)

        # Step 4: Exchange for access token (sandbox → apisb, live → api)
        access_token_url = f"{oauth_base}/oauth/access_token"
        oauth = OAuth1Session(
            self.key, client_secret=self.secret,
            resource_owner_key=resource_owner_key,
            resource_owner_secret=resource_owner_secret,
            verifier=verifier
        )
        oauth_tokens = oauth.fetch_access_token(access_token_url)

        self._save_token(oauth_tokens["oauth_token"], oauth_tokens["oauth_token_secret"])
        logger.info("E*Trade OAuth authentication successful")

    def _read_verifier(self, auth_url: str) -> str:
        """
        Read the OAuth verifier code in a TTY-safe way.

        - Interactive (TTY available): prompt via input(), same as before.
        - Headless (no TTY, e.g. nohup/launchd): write a pending-auth status
          file with the auth URL, then poll for the user to drop the verifier
          into config/.etrade_verifier. Times out after AUTH_TIMEOUT_SEC.

        This prevents the OSError: [Errno 5] Input/output error crash the
        agent used to hit on token expiry under nohup.
        """
        # Always write a pending-auth file so a headless operator can find
        # the URL even if they only see the log later.
        Path(AUTH_PENDING_FILE).write_text(json.dumps({
            "auth_url": auth_url,
            "instruction": (
                f"Visit the URL above, then run: "
                f"echo CODE > {AUTH_VERIFIER_FILE}"
            ),
            "since": datetime.now().isoformat(),
        }))

        # Try interactive prompt first if a TTY is attached.
        if sys.stdin and sys.stdin.isatty():
            try:
                verifier = input(
                    "Paste the verifier code from E*Trade here: "
                ).strip()
                if verifier:
                    Path(AUTH_PENDING_FILE).unlink(missing_ok=True)
                    return verifier
            except (EOFError, OSError) as e:
                # Stdin closed mid-prompt — fall through to file polling.
                logger.warning(
                    f"Interactive auth prompt unavailable ({e}); "
                    f"falling back to verifier-file polling."
                )

        # Headless path: poll for verifier file.
        verifier_path = Path(AUTH_VERIFIER_FILE)
        logger.warning("=" * 60)
        logger.warning("E*TRADE AUTH REQUIRED (headless mode)")
        logger.warning(f"  1. Open in a browser: {auth_url}")
        logger.warning(f"  2. After authorizing, copy the verifier code")
        logger.warning(f"  3. Run on this machine:")
        logger.warning(f"       echo YOUR_CODE > {AUTH_VERIFIER_FILE}")
        logger.warning(
            f"Polling every {AUTH_POLL_SEC}s for up to "
            f"{AUTH_TIMEOUT_SEC // 60} min..."
        )
        logger.warning("=" * 60)

        waited = 0
        while waited < AUTH_TIMEOUT_SEC:
            if verifier_path.exists():
                verifier = verifier_path.read_text().strip()
                # Consume the file so it can't be reused / left around.
                verifier_path.unlink(missing_ok=True)
                Path(AUTH_PENDING_FILE).unlink(missing_ok=True)
                if verifier:
                    logger.info("E*Trade verifier received from file")
                    return verifier
                logger.warning(
                    f"{AUTH_VERIFIER_FILE} was empty; continuing to wait."
                )
            time.sleep(AUTH_POLL_SEC)
            waited += AUTH_POLL_SEC

        # Timed out — let the caller decide what to do (agent.py retries).
        raise TimeoutError(
            f"E*Trade auth timed out after {AUTH_TIMEOUT_SEC // 60} min. "
            f"Visit {auth_url} and write the verifier to "
            f"{AUTH_VERIFIER_FILE} to retry."
        )

    def _save_token(self, token, token_secret):
        data = {"token": token, "secret": token_secret, "date": str(datetime.now().date())}
        Path(TOKEN_FILE).write_text(json.dumps(data))
        self._build_session(token, token_secret)

    def _load_token(self) -> bool:
        if not Path(TOKEN_FILE).exists():
            return False
        data = json.loads(Path(TOKEN_FILE).read_text())
        # E*Trade access tokens expire daily — auto-delete and re-auth
        if data.get("date") != str(datetime.now().date()):
            logger.info("E*Trade token expired — auto-deleting and re-authenticating")
            Path(TOKEN_FILE).unlink(missing_ok=True)
            return False
        self._build_session(data["token"], data["secret"])
        return True

    def _build_session(self, token, token_secret):
        self.session = OAuth1Session(
            self.key, client_secret=self.secret,
            resource_owner_key=token,
            resource_owner_secret=token_secret
        )

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account_id(self):
        """Fetch first account ID (used for order placement)."""
        url = f"{self.base}/v1/accounts/list.json"
        try:
            resp = self.session.get(url)
            resp.raise_for_status()
        except Exception as e:
            if "401" in str(e):
                logger.warning("401 on account fetch — token invalid, re-authenticating...")
                Path(TOKEN_FILE).unlink(missing_ok=True)
                self.authenticate()
                resp = self.session.get(url)
                resp.raise_for_status()
            else:
                raise
        accounts = resp.json()["AccountListResponse"]["Accounts"]["Account"]
        self.account_id = accounts[0]["accountIdKey"]
        logger.info(f"Using account: {self.account_id}")
        return self.account_id

    def get_buying_power(self) -> float:
        """Return available buying power."""
        if not self.account_id:
            self.get_account_id()
        url = f"{self.base}/v1/accounts/{self.account_id}/balance.json"
        params = {"instType": "BROKERAGE", "realTimeNAV": "true"}
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        bp = resp.json()["BalanceResponse"]["Computed"]["cashBuyingPower"]
        return float(bp)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    def place_order(self, symbol: str, action: str, quantity: int, dry_run: bool = False) -> dict:
        """
        Place a market order.
        action: "BUY" or "SELL"
        dry_run: preview only (no fill) — used for paper mode logging
        """
        if not self.account_id:
            self.get_account_id()

        if self.paper:
            # Paper mode: simulate locally, no API call needed
            logger.info(f"[PAPER] Simulated order: {action} {quantity} {symbol}")
            return {"simulated": True, "action": action, "symbol": symbol, "quantity": quantity, "status": "PAPER_FILLED"}

        # Live mode only
        order_payload = {
            "PlaceOrderRequest": {
                "orderType": "EQ",
                "clientOrderId": str(int(datetime.now().timestamp())),
                "Order": [{
                    "Instrument": [{
                        "Product": {"securityType": "EQ", "symbol": symbol},
                        "orderAction": action,
                        "quantityType": "QUANTITY",
                        "quantity": quantity,
                    }],
                    "orderTerm": "GOOD_FOR_DAY",
                    "priceType": "MARKET",
                    "marketSession": "REGULAR",
                }]
            }
        }
        url = f"{self.base}/v1/accounts/{self.account_id}/orders/place.json"
        logger.info(f"[LIVE] Placing order: {action} {quantity} {symbol}")
        resp = self.session.post(url, json=order_payload)
        resp.raise_for_status()
        result = resp.json()
        logger.info(f"Order response: {result}")
        return result

    def calculate_shares(self, price: float) -> int:
        """
        How many whole shares can we buy for TRADE_AMOUNT_USD?
        Returns 0 if price exceeds TRADE_AMOUNT_USD — agent will skip the trade.
        Never forces a minimum of 1 share — that would exceed the dollar limit.
        """
        if price <= 0:
            return 0
        shares = int(TRADE_AMOUNT_USD / price)
        return shares  # 0 means too expensive, agent.py will skip it
