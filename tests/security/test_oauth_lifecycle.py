from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from mvs.security.oauth import OAuthStore


async def test_pkce_state_isolation_refresh_revoke(tmp_path):
    store = OAuthStore(tmp_path)
    config = {
        "authorization_url": "https://id.example/authorize",
        "token_url": "https://id.example/token",
        "revocation_url": "https://id.example/revoke",
        "redirect_uri": "http://localhost/api/oauth/callback",
        "client_id": "mvs",
        "scope": "read",
    }
    url = store.begin("tenant/alice", "provider", config)
    query = parse_qs(urlsplit(url).query)
    assert query["code_challenge_method"] == ["S256"]
    observed = []

    def handler(request):
        values = parse_qs(request.content.decode())
        observed.append(values)
        if request.url.path == "/revoke":
            return httpx.Response(200, json={})
        if values["grant_type"] == ["authorization_code"]:
            assert "code_verifier" in values
            return httpx.Response(
                200, json={"access_token": "first", "refresh_token": "refresh", "expires_in": 0}
            )
        return httpx.Response(200, json={"access_token": "second", "expires_in": 3600})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await store.complete(query["state"][0], "code", {"provider": config}, client) == (
            "tenant/alice",
            "provider",
        )
        with pytest.raises(ValueError):
            await store.complete(query["state"][0], "code", {"provider": config}, client)
        with pytest.raises(ValueError):
            await store.access("tenant/bob", "provider", config, client)
        assert await store.access("tenant/alice", "provider", config, client) == "second"
        raw = store.db.execute("SELECT body FROM oauth_tokens").fetchone()[0]
        assert "refresh" not in raw and "second" not in raw
        await store.revoke("tenant/alice", "provider", config, client)
        with pytest.raises(ValueError):
            await store.access("tenant/alice", "provider", config, client)
    store.close()
