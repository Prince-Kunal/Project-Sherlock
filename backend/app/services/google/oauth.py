"""Google sign-in and Gmail authorisation (PLAN.md Phase 7), run by the backend.

The browser is sent to Google's consent screen (with PKCE and a state value bound to a cookie),
Google redirects back with a code, and the backend exchanges it for tokens. The refresh token is
stored Fernet-encrypted in `oauth_tokens` (invariant 6) and never reaches the frontend.

In Testing mode Google refresh tokens expire after about 7 days; refreshing then fails with
`invalid_grant`, which raises `GoogleReauthRequiredError` so the caller can pause sending.
"""

import base64
import contextlib
import hashlib
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import jwt

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 (a URL, not a secret)
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GMAIL_SEND = "https://www.googleapis.com/auth/gmail.send"
GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPES = ["openid", "email", "profile", GMAIL_SEND, GMAIL_READONLY]
GMAIL_SCOPES = {GMAIL_SEND, GMAIL_READONLY}
_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}


class GoogleAuthError(Exception):
    """Google refused the exchange or returned something unusable."""


class GoogleReauthRequiredError(GoogleAuthError):
    """The refresh token is expired or revoked (`invalid_grant`): the user must reconnect."""


@dataclass(frozen=True)
class GoogleIdentity:
    email: str
    email_verified: bool
    name: str
    subject: str  # Google's stable account id


@dataclass(frozen=True)
class GoogleTokens:
    identity: GoogleIdentity
    refresh_token: str | None  # absent if Google didn't issue a new one
    scopes: list[str]
    access_token: str
    expires_in: int


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_in: int


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge)."""
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


class GoogleOAuth(ABC):
    def __init__(self, client_id: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.redirect_uri = redirect_uri

    def authorization_url(self, state: str, code_challenge: str, login_hint: str | None = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            # A refresh token every time (needed again after a Testing-mode token expires).
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
        if login_hint:
            params["login_hint"] = login_hint
        return f"{AUTH_URL}?{urlencode(params)}"

    @abstractmethod
    async def exchange_code(self, code: str, code_verifier: str) -> GoogleTokens: ...

    @abstractmethod
    async def refresh(self, refresh_token: str) -> AccessToken: ...

    @abstractmethod
    async def revoke(self, token: str) -> None: ...


def identity_from_id_token(id_token: str, client_id: str) -> GoogleIdentity:
    """Claims of an ID token received straight from Google's token endpoint over TLS. OpenID Connect
    allows skipping the signature check for tokens obtained this way; audience, issuer and expiry
    are still checked."""
    try:
        claims: dict[str, Any] = jwt.decode(
            id_token,
            # With the signature check off, PyJWT skips the others unless they're switched on.
            options={
                "verify_signature": False,
                "verify_exp": True,
                "verify_aud": True,
                "require": ["iss", "aud", "exp", "sub"],
            },
            audience=client_id,
        )
    except jwt.PyJWTError as exc:
        raise GoogleAuthError(f"bad ID token: {exc}") from exc
    if claims.get("iss") not in _ISSUERS:
        raise GoogleAuthError("ID token from an unexpected issuer")
    return GoogleIdentity(
        email=str(claims.get("email", "")).lower(),
        email_verified=bool(claims.get("email_verified")),
        name=str(claims.get("name") or ""),
        subject=str(claims["sub"]),
    )


class HttpGoogleOAuth(GoogleOAuth):
    def __init__(
        self, client_id: str, client_secret: str, redirect_uri: str, client: httpx.AsyncClient | None = None
    ) -> None:
        super().__init__(client_id, redirect_uri)
        self._secret = client_secret
        self._client = client

    async def _post(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            response = await client.post(url, data=data)
        except httpx.TransportError as exc:
            raise GoogleAuthError(f"google: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            error = str(body.get("error", response.status_code))
            if error == "invalid_grant":
                raise GoogleReauthRequiredError(str(body.get("error_description", error)))
            raise GoogleAuthError(f"google {error}: {body.get('error_description', '')}".strip())
        return body

    async def exchange_code(self, code: str, code_verifier: str) -> GoogleTokens:
        body = await self._post(
            TOKEN_URL,
            {
                "code": code,
                "client_id": self.client_id,
                "client_secret": self._secret,
                "redirect_uri": self.redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
        if "id_token" not in body or "access_token" not in body:
            raise GoogleAuthError("google: token response without id_token/access_token")
        return GoogleTokens(
            identity=identity_from_id_token(body["id_token"], self.client_id),
            refresh_token=body.get("refresh_token"),
            scopes=str(body.get("scope", "")).split(),
            access_token=body["access_token"],
            expires_in=int(body.get("expires_in", 3600)),
        )

    async def refresh(self, refresh_token: str) -> AccessToken:
        body = await self._post(
            TOKEN_URL,
            {
                "refresh_token": refresh_token,
                "client_id": self.client_id,
                "client_secret": self._secret,
                "grant_type": "refresh_token",
            },
        )
        return AccessToken(token=body["access_token"], expires_in=int(body.get("expires_in", 3600)))

    async def revoke(self, token: str) -> None:
        with contextlib.suppress(GoogleAuthError):  # already revoked or expired: nothing to revoke
            await self._post(REVOKE_URL, {"token": token})
