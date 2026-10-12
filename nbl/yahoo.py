"""Minimal Yahoo Fantasy Sports API client (read-only, standard library only)."""
import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2/"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
RETRIES = 3  # extra attempts after a server-side failure


class YahooError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _urllib_transport(method, url, headers, body):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        return 599, str(error.reason).encode()


class YahooClient:
    def __init__(self, client_id, client_secret, refresh_token, transport=None, sleep=time.sleep):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self._transport = transport or _urllib_transport
        self._sleep = sleep
        self._access_token = None
        self.calls = 0

    def _refresh(self):
        basic = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        body = urllib.parse.urlencode(
            {"grant_type": "refresh_token", "refresh_token": self._refresh_token}
        ).encode()
        headers = {
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        status, payload = self._transport("POST", TOKEN_URL, headers, body)
        if status != 200:
            raise YahooError(
                f"Yahoo rejected the token refresh (HTTP {status}). Check that "
                "YAHOO_CLIENT_ID, YAHOO_CLIENT_SECRET and YAHOO_REFRESH_TOKEN are set "
                "correctly; if they are, run scripts/yahoo_auth.py again for a new "
                "YAHOO_REFRESH_TOKEN.",
                status,
            )
        self._access_token = json.loads(payload)["access_token"]

    def get(self, path):
        """GET one API path (relative to API_BASE) and return the raw XML bytes."""
        if self._access_token is None:
            self._refresh()
        reauthed = False
        failures = 0
        while True:
            headers = {"Authorization": f"Bearer {self._access_token}"}
            self.calls += 1
            status, body = self._transport("GET", API_BASE + path, headers, None)
            if status == 200:
                return body
            if status == 401 and not reauthed:
                reauthed = True
                self._refresh()
                continue
            if (status >= 500 or status == 999) and failures < RETRIES:
                failures += 1
                self._sleep(5 * failures)
                continue
            detail = body.decode("utf-8", "replace")[:300]
            raise YahooError(f"GET {path} failed (HTTP {status}): {detail}", status)
