"""Role-Based Access Control — simple role hierarchy.

Roles: admin > editor > viewer.
Higher roles inherit all permissions of lower roles.
"""

from __future__ import annotations

from metatron.core.exceptions import AuthenticationError
from metatron.core.models import Role

# Role hierarchy: index = privilege level (higher = more powerful)
_ROLE_LEVELS: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.EDITOR: 1,
    Role.ADMIN: 2,
}


def check_permission(user_role: Role, required_role: Role) -> bool:
    """Check if a user's role meets the required permission level.

    Args:
        user_role: The user's current role.
        required_role: Minimum role required for the action.

    Returns:
        True if the user has sufficient privileges.
    """
    return _ROLE_LEVELS.get(user_role, -1) >= _ROLE_LEVELS.get(required_role, 999)


def require_role(user_role: Role, required_role: Role) -> None:
    """Raise if user doesn't have the required role.

    Args:
        user_role: The user's current role.
        required_role: Minimum role required.

    Raises:
        AuthenticationError: If insufficient privileges.
    """
    if not check_permission(user_role, required_role):
        raise AuthenticationError(
            f"Requires {required_role.value} role, user has {user_role.value}"
        )
