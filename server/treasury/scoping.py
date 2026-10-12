
from .models import Entity, UserEntityAccess, UserRegionAccess
from users.models import UserProfile


def get_allowed_entities(user):
    """
    Return only the entities accessible to the user.
    """

    try:
        role = user.profile.role
    except UserProfile.DoesNotExist:
        return Entity.objects.none()

    # Admin can access every entity.
    if role == UserProfile.Role.ADMIN:
        return Entity.objects.all()

    # Analyst can access explicitly assigned entities.
    if role == UserProfile.Role.ANALYST:
        return Entity.objects.filter(
            user_accesses__user=user
            ).distinct()

    # Treasury Manager can access entities in assigned regions.
    if role == UserProfile.Role.TREASURY_MANAGER:
        return Entity.objects.filter(
            region__in=UserRegionAccess.objects.filter(
                user=user
            ).values("region")
        ).distinct()

    return Entity.objects.none()

