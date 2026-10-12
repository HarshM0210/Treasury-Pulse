"""Run ML Script 2 from the command line.

    python manage.py run_forecast              # only if data changed
    python manage.py run_forecast --force      # refit
    python manage.py run_forecast --as-of 2025-11-28 --force
"""
from django.core.management.base import BaseCommand

from ml.script2_forecast import run


class Command(BaseCommand):
    help = "Fit Prophet per entity and store the 30-day forecast + alerts."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--as-of", default=None)
        parser.add_argument("--calibrate", action="store_true", help="Apply bias calibration")

    def handle(self, force=False, as_of=None, calibrate=False, **opts):
        result = run(force=force, as_of=as_of, calibrate=calibrate or None)
        self.stdout.write(self.style.SUCCESS(f"{result['status']}: {result['forecast_run_id']}"))
        for name, e in result.get("entities", {}).items():
            self.stdout.write(f"  {name:20s} {e['worst_level']:10s} min {e['min_balance']:>18,.0f}  "
                              f"alert={e['alert']}  {e['method']} {e['seconds']}s")
