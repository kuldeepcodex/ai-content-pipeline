"""One-time helper: gets a LinkedIn access token (valid about 60 days).

Before running:
  1. Your LinkedIn app's Auth tab must list this redirect URL: http://localhost:8080/callback
  2. Your app's Products tab must have "Share on LinkedIn" and
     "Sign In with LinkedIn using OpenID Connect" enabled.
  3. LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET must be in .env

    python -m scripts.get_linkedin_token
"""
import http.server
import secrets
import sys
import urllib.parse
import webbrowser

import httpx

from src.config import require_env
import os

require_env("LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET")
CLIENT_ID = os.environ["LINKEDIN_CLIENT_ID"]
CLIENT_SECRET = os.environ["LINKEDIN_CLIENT_SECRET"]
REDIRECT = "http://localhost:8080/callback"
STATE = secrets.token_urlsafe(16)
result: dict = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if q.get("state", [""])[0] == STATE and "code" in q:
            result["code"] = q["code"][0]
            msg, code = b"Done. You can close this tab.", 200
        else:
            result["error"] = q.get("error_description", ["state mismatch or no code"])[0]
            msg, code = b"Something went wrong. Check the terminal.", 400
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(msg)

    def log_message(self, *args):
        pass


url = "https://www.linkedin.com/oauth/v2/authorization?" + urllib.parse.urlencode({
    "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT,
    "scope": "openid profile w_member_social", "state": STATE})
print("Opening your browser. If it does not open, visit:\n", url, "\n")
webbrowser.open(url)

server = http.server.HTTPServer(("localhost", 8080), Handler)
server.timeout = 180
server.handle_request()
server.server_close()

if "code" not in result:
    sys.exit(f"No authorization code: {result.get('error', 'timed out')}")

resp = httpx.post("https://www.linkedin.com/oauth/v2/accessToken", data={
    "grant_type": "authorization_code", "code": result["code"], "redirect_uri": REDIRECT,
    "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET}, timeout=20)
if resp.status_code != 200:
    sys.exit(f"Token exchange failed: {resp.status_code} {resp.text[:300]}")

data = resp.json()
print(f"\nSUCCESS. This token lasts about {int(data.get('expires_in', 0)) // 86400} days.")
print("Add this line to .env (and to your GitHub secrets):\n")
print(f"LINKEDIN_ACCESS_TOKEN={data['access_token']}\n")
