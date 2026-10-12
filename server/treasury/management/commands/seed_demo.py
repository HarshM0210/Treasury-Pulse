"""Create demo users with roles and data scope, and default thresholds.

    python manage.py seed_demo
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from treasury.ingestion import ensure_default_thresholds
from treasury.models import Entity, UserEntityAccess, UserRegionAccess
from users.models import UserProfile

User = get_user_model()

DEMO_USERS = [
    # username, password, role, first, last, entity name suffixes, regions
    ("admin", "admin12345", "ADMIN", "Ravi", "Patel", [], []),
    ("manager_emea", "manager12345", "TREASURY_MANAGER", "Sarah", "Kim", [], ["EMEA"]),
    ("manager_apac", "manager12345", "TREASURY_MANAGER", "Mei", "Tanaka", [], ["APAC"]),
    ("analyst_london", "analyst12345", "ANALYST", "John", "Doe", ["LONDON", "PARIS"], []),
    ("analyst_ny", "analyst12345", "ANALYST", "Lucas", "Meyer", ["NY", "SAO_PAULO"], []),
]


class Command(BaseCommand):
    help = "Create demo users (roles + scope) and default liquidity thresholds."

    def handle(self, *args, **opts):
        for username, password, role, first, last, entity_codes, regions in DEMO_USERS:
            user, created = User.objects.get_or_create(username=username, defaults={
                "first_name": first, "last_name": last, "email": f"{username}@treasurypulse.local",
                "is_staff": role == "ADMIN", "is_superuser": role == "ADMIN"})
            if created:
                user.set_password(password)
                user.save()
            UserProfile.objects.update_or_create(user=user, defaults={"role": role})
            for code in entity_codes:
                entity = Entity.objects.filter(name__iendswith=f"_{code}").first()
                if entity:
                    UserEntityAccess.objects.get_or_create(user=user, entity=entity)
            for region in regions:
                UserRegionAccess.objects.get_or_create(user=user, region=region)
            self.stdout.write(f"{'created' if created else 'exists '}  {username:16s} {role:17s} password: {password}")
        n = ensure_default_thresholds()
        self.stdout.write(self.style.SUCCESS(f"Thresholds created: {n}"))
        if not Entity.objects.exists():
            self.stdout.write(self.style.WARNING(
                "No entities yet: run `python manage.py import_transactions <csv>` then `seed_demo` again "
                "so analysts get their entity access."))
