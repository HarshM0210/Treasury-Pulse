
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from treasury.models import Entity, UserEntityAccess, UserRegionAccess

from .models import UserProfile
from .serializers import AdminUserSerializer

User = get_user_model()


def _set_scope(user, entity_ids=None, regions=None):
    """Replace a user's data scope (entities for Analysts, regions for Treasury Managers)."""
    if entity_ids is not None:
        UserEntityAccess.objects.filter(user=user).delete()
        for entity in Entity.objects.filter(id__in=entity_ids):
            UserEntityAccess.objects.create(user=user, entity=entity)
    if regions is not None:
        UserRegionAccess.objects.filter(user=user).delete()
        for region in sorted({str(r).upper() for r in regions if r}):
            UserRegionAccess.objects.create(user=user, region=region)


class AdminUserViewSet(viewsets.GenericViewSet):
    queryset = User.objects.all()
    serializer_class = AdminUserSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        self.check_admin()
        return User.objects.select_related("profile").order_by("id")

    def check_admin(self):
        try:
            if self.request.user.profile.role != UserProfile.Role.ADMIN:
                raise PermissionDenied(
                    "Only admins can manage user roles."
                )
        except UserProfile.DoesNotExist:
            raise PermissionDenied(
                "A Treasury Pulse role is required."
            )

    def list(self, request):
        self.check_admin()

        users = User.objects.select_related("profile").filter(profile__isnull=False).order_by("id")
        return Response(self.get_serializer(users, many=True).data)

    def create(self, request):
        """Create a user with a role and data scope."""
        self.check_admin()
        data = request.data
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        role = data.get("role", UserProfile.Role.ANALYST)
        if not username or len(password) < 8:
            return Response({"detail": "username and a password of at least 8 characters are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if role not in UserProfile.Role.values:
            return Response({"role": ["Choose ANALYST, TREASURY_MANAGER, or ADMIN."]},
                            status=status.HTTP_400_BAD_REQUEST)
        if User.objects.filter(username=username).exists():
            return Response({"detail": "That username is taken."}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            user = User.objects.create_user(
                username=username, password=password, email=data.get("email", ""),
                first_name=data.get("first_name", ""), last_name=data.get("last_name", ""),
            )
            UserProfile.objects.create(user=user, role=role)
            _set_scope(user, data.get("entities"), data.get("regions"))
        return Response(self.get_serializer(user).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        """Edit name, email, role and data scope."""
        self.check_admin()
        user = get_object_or_404(User.objects.select_related("profile"), pk=pk)
        data = request.data
        for field in ("email", "first_name", "last_name"):
            if field in data:
                setattr(user, field, data[field] or "")
        user.save()
        role = data.get("role")
        if role and role != user.profile.role:
            if user.pk == request.user.pk:
                return Response({"detail": "You cannot change your own role here."},
                                status=status.HTTP_400_BAD_REQUEST)
            if role not in UserProfile.Role.values:
                return Response({"role": ["Choose ANALYST, TREASURY_MANAGER, or ADMIN."]},
                                status=status.HTTP_400_BAD_REQUEST)
            user.profile.role = role
            user.profile.save(update_fields=["role"])
        _set_scope(user, data.get("entities"), data.get("regions"))
        return Response(self.get_serializer(user).data)

    @action(detail=True, methods=["patch"], url_path="role")
    def update_role(self, request, pk=None):
        self.check_admin()

        target_user = get_object_or_404(
            User.objects.select_related("profile"),
            pk=pk,
        )

        if target_user.pk == request.user.pk:
            return Response(
                {"detail": "You cannot change your own role here."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_role = request.data.get("role")
        if new_role not in UserProfile.Role.values:
            return Response(
                {
                    "role": [
                        "Choose ANALYST, TREASURY_MANAGER, or ADMIN."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_user.profile.role = new_role
        target_user.profile.save(update_fields=["role"])

        return Response(self.get_serializer(target_user).data)

    @action(detail=True, methods=["post"], url_path="set-active")
    def set_active(self, request, pk=None):
        """Suspend (is_active=false) or re-activate a user."""
        self.check_admin()
        user = get_object_or_404(User, pk=pk)
        if user.pk == request.user.pk:
            return Response({"detail": "You cannot suspend yourself."}, status=status.HTTP_400_BAD_REQUEST)
        user.is_active = bool(request.data.get("is_active"))
        user.save(update_fields=["is_active"])
        return Response(self.get_serializer(user).data)
