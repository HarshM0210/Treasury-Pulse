
from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import UserProfile

User = get_user_model()


class AdminUserSerializer(serializers.ModelSerializer):
    role = serializers.ChoiceField(
        choices=UserProfile.Role.choices,
        source="profile.role",
    )
    name = serializers.SerializerMethodField()
    entities = serializers.SerializerMethodField()
    regions = serializers.SerializerMethodField()
    scope = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "first_name", "last_name", "name",
                  "is_active", "entities", "regions", "scope"]
        read_only_fields = ["id", "username", "email"]

    def get_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_entities(self, obj):
        return list(obj.entity_accesses.values_list("entity_id", flat=True))

    def get_regions(self, obj):
        return list(obj.region_accesses.values_list("region", flat=True))

    def get_scope(self, obj):
        role = getattr(getattr(obj, "profile", None), "role", None)
        if role == UserProfile.Role.ADMIN:
            return "All data"
        if role == UserProfile.Role.TREASURY_MANAGER:
            return ", ".join(self.get_regions(obj)) or "No regions assigned"
        names = [a.entity.name.split("_", 1)[-1] for a in obj.entity_accesses.select_related("entity")]
        return ", ".join(names) or "No entities assigned"
