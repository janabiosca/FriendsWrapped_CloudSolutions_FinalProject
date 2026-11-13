"""Spotify client: how HTTP errors are translated and how the token request is built."""
import io
import os
import sys
import urllib.error
import urllib.parse

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import spotify  # noqa: E402


def http_error(code, body, headers=None):
    return urllib.error.HTTPError(spotify.TOKEN_URL, code, "error", headers or {}, io.BytesIO(body.encode()))


@pytest.fixture
def urlopen(monkeypatch):
    calls = {}

    def install(error=None, response=b'{"access_token": "a"}'):
        def fake(request, timeout=None):
            calls["request"] = request
            if error:
                raise error
            return io.BytesIO(response)
        monkeypatch.setattr(spotify.urllib.request, "urlopen", fake)
        return calls
    return install


def test_429_becomes_rate_limited_with_retry_after(urlopen):
    urlopen(http_error(429, "", {"Retry-After": "7"}))
    with pytest.raises(spotify.RateLimited) as e:
        spotify.recently_played("token")
    assert e.value.retry_after == 7


def test_invalid_grant_means_the_user_must_reconnect(urlopen):
    urlopen(http_error(400, '{"error": "invalid_grant", "error_description": "Refresh token revoked"}'))
    with pytest.raises(spotify.AuthRevoked):
        spotify.refresh("client", "old-refresh-token")


def test_other_errors_are_generic_and_keep_the_status(urlopen):
    urlopen(http_error(503, "Service Unavailable"))
    with pytest.raises(spotify.SpotifyError) as e:
        spotify.recently_played("token")
    assert not isinstance(e.value, (spotify.RateLimited, spotify.AuthRevoked))
    assert "HTTP 503" in str(e.value)


def test_pkce_refresh_sends_client_id_and_no_secret(urlopen):
    calls = urlopen()
    spotify.refresh("client", "refresh-token")
    form = urllib.parse.parse_qs(calls["request"].data.decode())
    assert form["client_id"] == ["client"] and form["grant_type"] == ["refresh_token"]
    assert "Authorization" not in calls["request"].headers


def test_recently_played_asks_for_plays_after_the_cursor(urlopen):
    calls = urlopen(response=b'{"items": []}')
    spotify.recently_played("token", after_ms=1762423200000)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(calls["request"].full_url).query)
    assert query == {"limit": ["50"], "after": ["1762423200000"]}
    assert calls["request"].headers["Authorization"] == "Bearer token"


def test_before_and_after_are_exclusive(urlopen):
    calls = urlopen(response=b'{"items": []}')
    spotify.recently_played("token", before_ms=123)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(calls["request"].full_url).query)
    assert query == {"limit": ["50"], "before": ["123"]}
    with pytest.raises(ValueError):
        spotify.recently_played("token", after_ms=1, before_ms=2)


@pytest.mark.parametrize("url", ["https://evil.example/v1/me/player/recently-played", "http://api.spotify.com/v1/me/player/recently-played", "https://api.spotify.com/v1/me/player"])
def test_pagination_never_forwards_tokens_to_other_endpoints(url):
    with pytest.raises(spotify.SpotifyError):
        spotify.next_recent_page("token", url)
