from __future__ import annotations

from dataclasses import dataclass


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

