from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass


PASSWORD_ITERATIONS = 310_000


class AuthenticationError(ValueError):
    pass


class AuthorizationError(PermissionError):
    pass


@dataclass(frozen=True)
class Principal:
    id: int
    organization_id: int
    username: str
    display_name: str
    role: str
    organization_name: str

    def require(self, *roles: str) -> None:
        if self.role not in roles:
            raise AuthorizationError("Bạn không có quyền thực hiện thao tác này.")


def principal_from_user(user: dict) -> Principal:
    return Principal(
        id=int(user["id"]),
        organization_id=int(user["organization_id"]),
        username=str(user["username"]),
        display_name=str(user["display_name"]),
        role=str(user["role"]),
        organization_name=str(user["organization_name"]),
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()

