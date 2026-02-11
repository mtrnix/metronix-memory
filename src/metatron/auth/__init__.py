"""Auth layer — JWT, RBAC, user mapping. Depends on core only."""

from metatron.auth.jwt import create_token, verify_token
from metatron.auth.rbac import Role, check_permission
from metatron.auth.user_mapping import map_platform_user

__all__ = [
    "create_token",
    "verify_token",
    "Role",
    "check_permission",
    "map_platform_user",
]
