#!/usr/bin/env python3
"""Yahoo Fantasy API - one-time refresh token helper.

Run:  python3 yahoo_auth.py
Needs only the Python standard library.
"""
import base64
import getpass
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

# Must match the Redirect URI registered in the Yahoo app exactly.
REDIRECT_URI = "https://localhost:8080/callback"
AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"


def extract_code(pasted: str) -> str:
    """Accept either the full redirected URL or just the code value."""
    pasted = pasted.strip()
    if "code=" in pasted:
        query = urllib.parse.urlparse(pasted).query
        values = urllib.parse.parse_qs(query).get("code")
        if values:
            return values[0]
    return pasted


def main() -> None:
    print("=== Yahoo refresh token helper ===\n")
    client_id = input("1) Client ID 붙여넣기: ").strip()
    client_secret = getpass.getpass("2) Client Secret 붙여넣기 (화면에 표시되지 않음): ").strip()
    if not client_id or not client_secret:
        sys.exit("Client ID와 Client Secret이 모두 필요합니다.")

    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
        }
    )
    url = f"{AUTH_URL}?{params}"
    print("\n3) 브라우저에서 Yahoo 로그인 후 '동의(Agree)'를 누르세요.")
    print("   브라우저가 자동으로 열리지 않으면 아래 주소를 복사해 여세요:\n")
    print(f"   {url}\n")
    webbrowser.open(url)

    print("4) 동의하면 'localhost 연결할 수 없음' 화면이 뜹니다. 정상입니다.")
    pasted = input("   그 화면의 주소창 전체 주소를 복사해 붙여넣기: ")
    code = extract_code(pasted)
    if not code:
        sys.exit("code 값을 찾지 못했습니다. 주소 전체를 다시 복사해 주세요.")

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
        }
    ).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=body,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            tokens = json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        sys.exit(
            f"\n토큰 발급 실패 (HTTP {error.code}): {detail}\n"
            "code는 몇 분 안에 만료되고 한 번만 쓸 수 있습니다. 처음부터 다시 실행해 주세요."
        )

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        sys.exit(f"\n응답에 refresh_token이 없습니다: {tokens}")

    print("\n=== 성공 ===")
    print("아래 값을 GitHub Secrets의 YAHOO_REFRESH_TOKEN에 넣으세요.")
    print("이 값은 다른 곳(채팅 포함)에 공유하지 마세요.\n")
    print(refresh_token)
    print()


if __name__ == "__main__":
    main()
