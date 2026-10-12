import base64
import json
import unittest
import urllib.parse

from nbl.yahoo import API_BASE, TOKEN_URL, YahooClient, YahooError


class FakeTransport:
    """Stands in for the network: answers from a queue and records requests."""

    def __init__(self, api_responses, token_status=200):
        self.api_responses = list(api_responses)
        self.token_status = token_status
        self.requests = []
        self.tokens_issued = 0

    def __call__(self, method, url, headers, body):
        self.requests.append({"method": method, "url": url, "headers": headers, "body": body})
        if url == TOKEN_URL:
            if self.token_status != 200:
                return self.token_status, (
                    b'{"error":"invalid_grant","error_description":"Invalid refresh token"}'
                )
            self.tokens_issued += 1
            token = f"access-{self.tokens_issued}"
            return 200, json.dumps({"access_token": token, "expires_in": 3600}).encode()
        return self.api_responses.pop(0)

    def api_requests(self):
        return [r for r in self.requests if r["url"] != TOKEN_URL]

    def token_requests(self):
        return [r for r in self.requests if r["url"] == TOKEN_URL]


def client(transport):
    return YahooClient("my-id", "my-secret", "my-refresh", transport=transport, sleep=lambda s: None)


class YahooClientTests(unittest.TestCase):
    def test_get_returns_body_from_api_url_with_bearer_token(self):
        t = FakeTransport([(200, b"<ok/>")])
        body = client(t).get("league/470.l.80126/standings")
        self.assertEqual(body, b"<ok/>")
        req = t.api_requests()[0]
        self.assertEqual(req["url"], API_BASE + "league/470.l.80126/standings")
        self.assertEqual(req["headers"]["Authorization"], "Bearer access-1")

    def test_token_request_uses_basic_auth_and_refresh_grant(self):
        t = FakeTransport([(200, b"<ok/>")])
        client(t).get("x")
        req = t.token_requests()[0]
        self.assertEqual(req["method"], "POST")
        expected = base64.b64encode(b"my-id:my-secret").decode()
        self.assertEqual(req["headers"]["Authorization"], f"Basic {expected}")
        form = urllib.parse.parse_qs(req["body"].decode())
        self.assertEqual(form["grant_type"], ["refresh_token"])
        self.assertEqual(form["refresh_token"], ["my-refresh"])

    def test_token_request_sends_the_registered_redirect_uri(self):
        # Yahoo's documented refresh request includes redirect_uri.
        t = FakeTransport([(200, b"<ok/>")])
        client(t).get("x")
        form = urllib.parse.parse_qs(t.token_requests()[0]["body"].decode())
        self.assertEqual(form["redirect_uri"], ["https://localhost:8080/callback"])

    def test_redirect_uri_can_be_overridden(self):
        t = FakeTransport([(200, b"<ok/>")])
        YahooClient("i", "s", "r", transport=t, redirect_uri="oob").get("x")
        form = urllib.parse.parse_qs(t.token_requests()[0]["body"].decode())
        self.assertEqual(form["redirect_uri"], ["oob"])

    def test_credentials_are_trimmed_of_pasted_whitespace(self):
        t = FakeTransport([(200, b"<ok/>")])
        YahooClient(" my-id\n", "my-secret \n", "\tmy-refresh\n", transport=t).get("x")
        req = t.token_requests()[0]
        expected = base64.b64encode(b"my-id:my-secret").decode()
        self.assertEqual(req["headers"]["Authorization"], f"Basic {expected}")
        form = urllib.parse.parse_qs(req["body"].decode())
        self.assertEqual(form["refresh_token"], ["my-refresh"])

    def test_rejected_refresh_reports_yahoos_own_reason(self):
        t = FakeTransport([], token_status=400)
        with self.assertRaises(YahooError) as ctx:
            client(t).get("x")
        message = str(ctx.exception)
        self.assertIn("invalid_grant", message)
        self.assertIn("Invalid refresh token", message)

    def test_empty_credential_does_not_garble_the_error_message(self):
        t = FakeTransport([], token_status=400)
        with self.assertRaises(YahooError) as ctx:
            YahooClient("id", "", "", transport=t).get("x")
        self.assertIn("invalid_grant - Invalid refresh token", str(ctx.exception))

    def test_rejected_refresh_with_unreadable_body_still_reports_status(self):
        class Html(FakeTransport):
            def __call__(self, method, url, headers, body):
                return 400, b"<html>Bad Request</html>"

        with self.assertRaises(YahooError) as ctx:
            client(Html([])).get("x")
        self.assertIn("HTTP 400", str(ctx.exception))
        self.assertIn("Bad Request", str(ctx.exception))

    def test_access_token_is_reused_between_calls(self):
        t = FakeTransport([(200, b"a"), (200, b"b")])
        c = client(t)
        c.get("one")
        c.get("two")
        self.assertEqual(len(t.token_requests()), 1)

    def test_expired_token_is_refreshed_and_request_retried(self):
        t = FakeTransport([(401, b"token expired"), (200, b"fine")])
        self.assertEqual(client(t).get("x"), b"fine")
        self.assertEqual(len(t.token_requests()), 2)
        self.assertEqual(t.api_requests()[1]["headers"]["Authorization"], "Bearer access-2")

    def test_server_errors_are_retried(self):
        t = FakeTransport([(503, b"busy"), (999, b"throttled"), (200, b"fine")])
        self.assertEqual(client(t).get("x"), b"fine")

    def test_gives_up_after_repeated_server_errors(self):
        t = FakeTransport([(503, b"busy")] * 4)
        with self.assertRaises(YahooError) as ctx:
            client(t).get("league/x/standings")
        self.assertEqual(ctx.exception.status, 503)
        self.assertIn("league/x/standings", str(ctx.exception))
        self.assertEqual(len(t.api_requests()), 4)

    def test_client_error_fails_immediately_with_response_text(self):
        t = FakeTransport([(400, b"<error>Invalid league key</error>")])
        with self.assertRaises(YahooError) as ctx:
            client(t).get("league/bad")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("Invalid league key", str(ctx.exception))
        self.assertEqual(len(t.api_requests()), 1)

    def test_rejected_refresh_token_explains_what_to_fix(self):
        t = FakeTransport([], token_status=400)
        with self.assertRaises(YahooError) as ctx:
            client(t).get("x")
        message = str(ctx.exception)
        self.assertIn("YAHOO_REFRESH_TOKEN", message)
        self.assertNotIn("my-secret", message)
        self.assertNotIn("my-refresh", message)


if __name__ == "__main__":
    unittest.main()
