"""Fake Google OAuth for tests and USE_FAKES=true: the code is the email address to sign in as."""

from app.services.google.oauth import (
    SCOPES,
    AccessToken,
    GoogleAuthError,
    GoogleIdentity,
    GoogleOAuth,
    GoogleReauthRequiredError,
    GoogleTokens,
)


class FakeGoogleOAuth(GoogleOAuth):
    def __init__(self, client_id: str = "fake-client", redirect_uri: str = "http://test/callback") -> None:
        super().__init__(client_id, redirect_uri)
        self.scopes = list(SCOPES)  # set to fewer to simulate unticked Gmail permissions
        self.expired: set[str] = set()  # refresh tokens that fail with invalid_grant
        self.revoked: list[str] = []
        self.verifiers: list[str] = []
        self.refreshes = 0

    async def exchange_code(self, code: str, code_verifier: str) -> GoogleTokens:
        if "@" not in code:
            raise GoogleAuthError("fake: bad code")
        self.verifiers.append(code_verifier)
        email = code.lower()
        return GoogleTokens(
            identity=GoogleIdentity(
                email=email, email_verified=True, name=email.split("@")[0].title(), subject=f"sub-{email}"
            ),
            refresh_token=f"refresh-{email}",
            scopes=list(self.scopes),
            access_token=f"access-{email}",
            expires_in=3600,
        )

    async def refresh(self, refresh_token: str) -> AccessToken:
        self.refreshes += 1
        if refresh_token in self.expired:
            raise GoogleReauthRequiredError("fake: Token has been expired or revoked.")
        return AccessToken(token=f"access-for-{refresh_token}", expires_in=3600)

    async def revoke(self, token: str) -> None:
        self.revoked.append(token)
