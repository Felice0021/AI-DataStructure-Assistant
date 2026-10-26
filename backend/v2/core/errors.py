class AuthError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def unauthorized() -> AuthError:
    return AuthError(401, "unauthorized", "Authentication required", {"WWW-Authenticate": "Session"})
