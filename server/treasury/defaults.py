"""Shared defaults for thresholds and FX, used by ingestion, the API and the ML pipeline."""
from decimal import Decimal

# Minimum cash thresholds per currency.
# EUR / USD / GBP / JPY come from the problem statement; the others are
# the USD 60,000 equivalent at the dataset's own FX rates (rounded).
DEFAULT_THRESHOLDS = {
    "EUR": Decimal("50000"),
    "USD": Decimal("60000"),
    "GBP": Decimal("40000"),
    "JPY": Decimal("5000000"),
    "AED": Decimal("220000"),
    "BRL": Decimal("355000"),
    "HKD": Decimal("470000"),
    "INR": Decimal("5000000"),
    "SGD": Decimal("81000"),
    "CHF": Decimal("54000"),
}
FALLBACK_THRESHOLD = Decimal("60000")


def default_threshold(currency):
    return DEFAULT_THRESHOLDS.get((currency or "").upper(), FALLBACK_THRESHOLD)
