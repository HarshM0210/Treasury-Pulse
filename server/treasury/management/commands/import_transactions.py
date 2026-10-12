"""Import the transactions CSV, rebuild cash positions and run the forecast (Script 2).

    python manage.py import_transactions "UC5 - sample_transactions v3.csv"
"""
from django.core.management.base import BaseCommand, CommandError

from ml.script1_prepare import invalidate_cache
from ml.script2_forecast import run as run_forecast
from treasury.ingestion import import_csv_dataset, ingest_csv


class Command(BaseCommand):
    help = "Validate + import a transactions CSV, rebuild positions, run the ML forecast."

    def add_arguments(self, parser):
        parser.add_argument("csv_path")
        parser.add_argument("--dry-run", action="store_true", help="Validate only")
        parser.add_argument("--skip-forecast", action="store_true")

    def handle(self, csv_path, dry_run=False, skip_forecast=False, **opts):
        try:
            if dry_run:
                self.stdout.write(str(import_csv_dataset(csv_path, dry_run=True)))
                return
            stats = ingest_csv(csv_path)
        except (ValueError, FileNotFoundError) as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(f"Imported: {stats}"))
        if not skip_forecast:
            invalidate_cache()
            result = run_forecast(force=True)
            self.stdout.write(self.style.SUCCESS(
                f"Forecast {result['forecast_run_id']} in {result['elapsed_seconds']}s"))
