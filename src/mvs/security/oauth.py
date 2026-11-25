"""OAuth2授权码+PKCE，状态一次性消费，令牌加密保存与续期/撤销。"""

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx

from mvs.infrastructure.storage.control_db import control_database
from mvs.security.vault import Vault


class OAuthStore:
    def __init__(self, root: Path) -> None:
        self.vault = Vault(root)
        self.db = control_database(root / "oauth.sqlite3")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS oauth_states "
            "(state TEXT PRIMARY KEY, owner TEXT, provider TEXT, verifier TEXT, expires REAL)"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS oauth_tokens "
            "(owner TEXT,provider TEXT,body TEXT,PRIMARY KEY(owner,provider))"
        )
        self.db.commit()

    @staticmethod
    def validate(config: dict) -> None:
        for key in (
            "authorization_url",
            "token_url",
            *(["revocation_url"] if config.get("revocation_url") else []),
        ):
            parsed = urlsplit(config[key])
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.fragment
            ):
                raise ValueError("OAuth端点必须为HTTPS")
        callback = urlsplit(config["redirect_uri"])
        if callback.scheme != "https" and not (
            callback.scheme == "http" and callback.hostname in {"127.0.0.1", "localhost"}
        ):
            raise ValueError("回调仅允许HTTPS或本机HTTP")
        if not config["client_id"]:
            raise ValueError("client_id不能为空")

    def begin(self, owner: str, provider: str, config: dict) -> str:
        self.validate(config)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        with self.db:
            self.db.execute("DELETE FROM oauth_states WHERE expires<?", (time.time(),))
            self.db.execute(
                "INSERT INTO oauth_states VALUES (?,?,?,?,?)",
                (
                    state,
                    owner,
                    provider,
                    json.dumps(self.vault.seal({"verifier": verifier})),
                    time.time() + 300,
                ),
            )
        return (
            config["authorization_url"]
            + "?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": config["client_id"],
                    "redirect_uri": config["redirect_uri"],
                    "scope": config.get("scope", ""),
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )

    async def complete(
        self, state: str, code: str, configs: dict, client: httpx.AsyncClient
    ) -> tuple[str, str]:
        with self.db:
            row = self.db.execute(
                "DELETE FROM oauth_states WHERE state=? AND expires>? "
                "RETURNING owner,provider,verifier",
                (state, time.time()),
            ).fetchone()
        if row is None:
            raise ValueError("OAuth状态无效、已使用或过期")
        owner, provider, encrypted = row
        config = configs[provider]
        self.validate(config)
        verifier = self.vault.open(json.loads(encrypted))["verifier"]
        response = await client.post(
            config["token_url"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": config["client_id"],
                "redirect_uri": config["redirect_uri"],
                "code_verifier": verifier,
                **(
                    {"client_secret": os.environ[config["client_secret_ref"]]}
                    if config.get("client_secret_ref")
                    else {}
                ),
            },
        )
        if response.status_code != 200:
            raise ValueError("OAuth令牌交换失败")
        self.save(owner, provider, response.json())
        return owner, provider

    def save(self, owner: str, provider: str, token: dict) -> None:
        if not token.get("access_token"):
            raise ValueError("OAuth响应缺少access_token")
        token["expires_at"] = time.time() + int(token.get("expires_in", 3600))
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO oauth_tokens VALUES (?,?,?)",
                (owner, provider, json.dumps(self.vault.seal(token))),
            )

    async def access(
        self, owner: str, provider: str, config: dict, client: httpx.AsyncClient
    ) -> str:
        row = self.db.execute(
            "SELECT body FROM oauth_tokens WHERE owner=? AND provider=?", (owner, provider)
        ).fetchone()
        if row is None:
            raise ValueError("尚未授权OAuth")
        token = self.vault.open(json.loads(row[0]))
        if token["expires_at"] <= time.time() + 30:
            if not token.get("refresh_token"):
                raise ValueError("授权已过期，需要重新登录")
            response = await client.post(
                config["token_url"],
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": token["refresh_token"],
                    "client_id": config["client_id"],
                    **(
                        {"client_secret": os.environ[config["client_secret_ref"]]}
                        if config.get("client_secret_ref")
                        else {}
                    ),
                },
            )
            if response.status_code != 200:
                raise ValueError("OAuth续期失败")
            token = {**token, **response.json()}
            self.save(owner, provider, token)
        return token["access_token"]

    async def revoke(
        self, owner: str, provider: str, config: dict, client: httpx.AsyncClient
    ) -> None:
        row = self.db.execute(
            "SELECT body FROM oauth_tokens WHERE owner=? AND provider=?", (owner, provider)
        ).fetchone()
        if row and config.get("revocation_url"):
            token = self.vault.open(json.loads(row[0]))
            response = await client.post(
                config["revocation_url"],
                data={
                    "token": token.get("refresh_token", token["access_token"]),
                    "client_id": config["client_id"],
                },
            )
            if response.status_code not in {200, 204}:
                raise ValueError("远端撤销失败")
        with self.db:
            self.db.execute(
                "DELETE FROM oauth_tokens WHERE owner=? AND provider=?", (owner, provider)
            )

    def close(self) -> None:
        self.db.close()
