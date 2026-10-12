
from rest_framework.permissions import BasePermission

from users.models import UserProfile


class IsTreasuryUser(BasePermission):
    """
    Allow access only to authenticated users
    with a valid Treasury Pulse role.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        try:
            role = user.profile.role
        except UserProfile.DoesNotExist:
            return False

        return role in [
            UserProfile.Role.ANALYST,
            UserProfile.Role.TREASURY_MANAGER,
            UserProfile.Role.ADMIN,
        ]


class IsAdminRole(BasePermission):
    """
    Allow access only to authenticated users
    whose Treasury Pulse role is Admin.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        try:
            return user.profile.role == UserProfile.Role.ADMIN
        except UserProfile.DoesNotExist:
            return False


class CanManageTreasuryData(BasePermission):
    """
    All authorized Treasury users can read.
    Only Admins can create, update, or delete.
    """

    def has_permission(self, request, view):
        user = request.user

        if not user or not user.is_authenticated:
            return False

        # Validate that the user has a Treasury role.
        try:
            role = user.profile.role
        except UserProfile.DoesNotExist:
            return False

        if role not in UserProfile.Role.values:
            return False

        # Read-only requests are allowed for all valid roles.
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True

        # Write operations are Admin-only.
        return role == UserProfile.Role.ADMIN
