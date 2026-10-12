
from django.conf import settings
from django.db import models


class UserProfile(models.Model):
    class Role(models.TextChoices):
        ANALYST = "ANALYST", "Analyst"
        TREASURY_MANAGER = "TREASURY_MANAGER", "Treasury Manager"
        ADMIN = "ADMIN", "Admin"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(
        max_length=30,
        choices=Role.choices,
        default=Role.ANALYST,
    )

    def __str__(self):
        return f"{self.user.username} - {self.role}"
