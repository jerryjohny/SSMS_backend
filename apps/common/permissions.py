from rest_framework.permissions import BasePermission, SAFE_METHODS

from apps.accounts.models import User


def user_has_role(user, *roles: str) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return getattr(user, "role", "") in roles


class IsTenantAdminOrSysAdmin(BasePermission):
    def has_permission(self, request, view):
        return user_has_role(
            request.user,
            User.Role.ADMIN,
            User.Role.SYSADMIN,
        )


class IsTenantSysAdmin(BasePermission):
    def has_permission(self, request, view):
        return user_has_role(request.user, User.Role.SYSADMIN)


class ReadOnlyOrAdminOrSysAdmin(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return getattr(request.user, "is_authenticated", False)
        return user_has_role(
            request.user,
            User.Role.ADMIN,
            User.Role.SYSADMIN,
        )


class ReadOnlyOrSysAdmin(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return getattr(request.user, "is_authenticated", False)
        return user_has_role(request.user, User.Role.SYSADMIN)
