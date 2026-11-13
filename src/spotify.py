"""Minimal Spotify Web API client. Standard library only, so the Lambdas need no dependencies."""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request

TOKEN_URL = "https://accounts.spotify.com/api/token"
API_URL = "https://api.spotify.com/v1"
PAGE_SIZE = 50  # Maximum per request; availability of older history is not guaranteed.


class SpotifyError(Exception):
    pass


class RateLimited(SpotifyError):
    def __init__(self, retry_after):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


class AuthRevoked(SpotifyError):
    """The refresh token is no longer valid: the user has to connect Spotify again."""


def _call(request):
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.load(response)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        if e.code == 429:
            raise RateLimited(int(e.headers.get("Retry-After", "1"))) from e
        if "invalid_grant" in body:
            raise AuthRevoked(body) from e
        raise SpotifyError(f"HTTP {e.code}: {body}") from e


def refresh(client_id, refresh_token, client_secret=None):
    """Exchanges a refresh token for an access token.

    The response may carry a new refresh token (PKCE apps rotate them); the caller must store it.
    """
    form = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if client_secret:
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
    else:
        form["client_id"] = client_id
    data = urllib.parse.urlencode(form).encode()
    return _call(urllib.request.Request(TOKEN_URL, data=data, headers=headers))


def recently_played(access_token, after_ms=None, before_ms=None):
    """Plays after the given cursor (unix ms, exclusive), newest first, at most PAGE_SIZE."""
    if after_ms is not None and before_ms is not None:
        raise ValueError("after and before cannot be combined")
    params = {"limit": PAGE_SIZE}
    if after_ms:
        params["after"] = after_ms
    if before_ms is not None:
        params["before"] = before_ms
    url = f"{API_URL}/me/player/recently-played?{urllib.parse.urlencode(params)}"
    return _call(urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"}))


def next_recent_page(access_token, url):
    """Follow only Spotify's documented history endpoint; never forward tokens elsewhere."""
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc != "api.spotify.com"
            or parsed.path != "/v1/me/player/recently-played" or parsed.fragment):
        raise SpotifyError("Unexpected pagination URL")
    return _call(urllib.request.Request(url, headers={"Authorization": f"Bearer {access_token}"}))
