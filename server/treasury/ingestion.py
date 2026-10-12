
import csv
import math
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, Sum

from .defaults import default_threshold
from .models import BankAccount, CashPosition, Entity, LiquidityThreshold, Transaction


REQUIRED_COLUMNS = {
    "transaction_id",
    "due_date(expected)",
    "transaction_date(Actual)",
    "entity",
    "region",
    "country",
    "account_number",
    "currency",
    "original_amount",
    "direction",
    "settlement_status",
    "origin_currency",
    "destination_currency",
    "fx_rate",
}

# Columns the ML pipeline uses. Optional: if a CSV lacks them the import
# still works, and the pipeline falls back to neutral defaults.
OPTIONAL_COLUMNS = {
    "counterparty",
    "product_type",
    "category",
    "department",
    "frequency",
    "is_recurring",
    "is_cross_border",
    "interest_rate",
    "maturity_date",
}


def validate_csv_headers(fieldnames):
    """Ensure the uploaded CSV contains all required columns."""
    if not fieldnames:
        raise ValueError("The CSV file is empty or has no header row.")

    missing = REQUIRED_COLUMNS - set(fieldnames)

    if missing:
        raise ValueError(
            "Missing required CSV columns: " + ", ".join(sorted(missing))
        )


def parse_csv_date(value, field_name, required=False):
    """Parse dates in the dataset's M/D/YYYY format (ISO YYYY-MM-DD also accepted)."""
    value = (value or "").strip()

    if not value:
        if required:
            raise ValueError(f"{field_name} is required.")
        return None

    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date in {field_name}: {value!r}")


def parse_csv_decimal(value, field_name, required=True):
    """Parse a decimal value without using floating-point arithmetic."""
    value = (value or "").strip()

    if not value:
        if required:
            raise ValueError(f"{field_name} is required.")
        return None

    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(
            f"Invalid decimal in {field_name}: {value!r}"
        ) from exc

    if not result.is_finite():
        raise ValueError(f"{field_name} must be a finite number.")

    return result


def parse_csv_bool(value):
    value = (value or "").strip().lower()
    if value in {"yes", "true", "1", "y"}:
        return True
    if value in {"no", "false", "0", "n"}:
        return False
    return None


def normalize_transaction(row):
    """Validate and normalize one CSV transaction row."""
    transaction_id = (row.get("transaction_id") or "").strip()
    entity_name = (row.get("entity") or "").strip()
    region = (row.get("region") or "").strip().upper()
    country = (row.get("country") or "").strip()
    direction = (row.get("direction") or "").strip().lower()
    settlement_status = (
        (row.get("settlement_status") or "").strip().lower()
    )

    if not transaction_id:
        raise ValueError("transaction_id is required.")

    if not entity_name or not region or not country:
        raise ValueError(
            f"{transaction_id}: entity, region, and country are required."
        )

    if direction not in {"inflow", "outflow"}:
        raise ValueError(
            f"{transaction_id}: invalid direction {direction!r}."
        )

    if settlement_status not in {"settled", "failed"}:
        raise ValueError(
            f"{transaction_id}: invalid settlement_status "
            f"{settlement_status!r}."
        )

    currency = (row.get("currency") or "").strip().upper()
    origin_currency = (
        (row.get("origin_currency") or "").strip().upper()
    )
    destination_currency = (
        (row.get("destination_currency") or "").strip().upper()
    )

    if not all((currency, origin_currency, destination_currency)):
        raise ValueError(
            f"{transaction_id}: currency fields are required."
        )

    original_amount = parse_csv_decimal(
        row.get("original_amount"), "original_amount"
    )

    if original_amount < 0:
        raise ValueError(
            f"{transaction_id}: original_amount cannot be negative."
        )

    fx_rate = parse_csv_decimal(row.get("fx_rate"), "fx_rate")

    if fx_rate <= 0:
        raise ValueError(
            f"{transaction_id}: fx_rate must be greater than zero."
        )

    # The dataset defines original_amount in destination_currency.
    # Inflows are denominated in the entity currency.
    # For outflows, origin_currency is the entity currency.
    if direction == "inflow":
        amount = original_amount
        normalized_currency = destination_currency
    else:
        amount = original_amount * fx_rate
        normalized_currency = origin_currency

    interest_rate = parse_csv_decimal(
        row.get("interest_rate"), "interest_rate", required=False
    )

    return {
        "transaction_id": transaction_id,
        "entity_name": entity_name,
        "region": region,
        "country": country,
        "transaction_date": parse_csv_date(
            row.get("transaction_date(Actual)"),
            "transaction_date(Actual)",
            required=True,
        ),
        "due_date": parse_csv_date(
            row.get("due_date(expected)"),
            "due_date(expected)",
        ),
        "amount": amount,
        "currency": normalized_currency,
        "account_currency": currency,
        "direction": direction,
        "settlement_status": settlement_status,
        "original_amount": original_amount,
        "origin_currency": origin_currency,
        "destination_currency": destination_currency,
        "fx_rate": fx_rate,
        "account_number": (
            row.get("account_number") or ""
        ).strip(),
        # ML fields (optional columns)
        "counterparty": (row.get("counterparty") or "").strip(),
        "product_type": (row.get("product_type") or "").strip().lower(),
        "category": (row.get("category") or "").strip().lower(),
        "department": (row.get("department") or "").strip().lower(),
        "frequency": (row.get("frequency") or "").strip().lower(),
        "is_recurring": parse_csv_bool(row.get("is_recurring")),
        "is_cross_border": (
            parse_csv_bool(row.get("is_cross_border"))
            if (row.get("is_cross_border") or "").strip()
            else origin_currency != destination_currency
        ),
        "interest_rate": interest_rate,
        "maturity_date": parse_csv_date(
            row.get("maturity_date"), "maturity_date"
        ),
    }


ML_FIELDS = [
    "counterparty", "product_type", "category", "department", "frequency",
    "is_recurring", "is_cross_border", "interest_rate", "maturity_date",
]

COUNTRY_ALIASES = {
    "HK": "Hong Kong",
    "Hong Kong": "Hong Kong",
}


def import_csv_dataset(file_path, dry_run=True):
    """
    Validate and import CSV transactions.

    dry_run=True validates the entire file without saving database changes.
    Existing records are preserved. Duplicate transaction IDs are skipped.
    """
    stats = {
        "rows_read": 0,
        "valid_rows": 0,
        "new_transactions": 0,
        "duplicate_transactions": 0,
        "entities_created": 0,
        "accounts_created": 0,
    }

    # First pass: validate all rows before writing anything.
    rows = []
    with open(file_path, newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        validate_csv_headers(reader.fieldnames)
        stats["optional_columns_missing"] = sorted(
            OPTIONAL_COLUMNS - set(reader.fieldnames)
        )

        for line_number, row in enumerate(reader, start=2):
            stats["rows_read"] += 1
            try:
                data = normalize_transaction(row)
            except (ValueError, TypeError) as exc:
                raise ValueError(f"CSV line {line_number}: {exc}") from exc

            data["country"] = COUNTRY_ALIASES.get(data["country"], data["country"])
            rows.append(data)
            stats["valid_rows"] += 1

    if dry_run:
        return stats

    with transaction.atomic():
        # Entities: one get_or_create per distinct entity, not per row.
        entities = {}
        for data in rows:
            name = data["entity_name"]
            if name in entities:
                entity = entities[name]
            else:
                entity, created = Entity.objects.get_or_create(
                    name=name,
                    defaults={"region": data["region"], "country": data["country"]},
                )
                if created:
                    stats["entities_created"] += 1
                entities[name] = entity

            # Refuse to silently change existing entity metadata.
            if entity.region != data["region"] or entity.country != data["country"]:
                raise ValueError(f"Entity metadata mismatch for {entity.name}")

        # Bank accounts
        existing_accounts = {
            (a.entity_id, a.account_number): a
            for a in BankAccount.objects.filter(entity__in=entities.values())
        }
        new_accounts = {}
        for data in rows:
            entity = entities[data["entity_name"]]
            key = (entity.id, data["account_number"])
            account = existing_accounts.get(key) or new_accounts.get(key)
            if account is None:
                new_accounts[key] = BankAccount(
                    entity=entity,
                    account_number=data["account_number"],
                    currency=data["account_currency"],
                )
            elif account.currency != data["account_currency"]:
                raise ValueError(
                    f"Account currency mismatch for {data['account_number']}"
                )
        BankAccount.objects.bulk_create(new_accounts.values(), batch_size=1000)
        stats["accounts_created"] = len(new_accounts)

        # Transactions: skip IDs already in the database or repeated in the file.
        # Rows imported before the ML columns existed get those columns backfilled.
        existing = dict(
            Transaction.objects.values_list("transaction_id", "counterparty")
        )
        existing_ids = set(existing)
        backfill = {}
        to_create = []
        for data in rows:
            if data["transaction_id"] in existing_ids:
                stats["duplicate_transactions"] += 1
                if not existing.get(data["transaction_id"]) and data["counterparty"]:
                    backfill[data["transaction_id"]] = data
                continue
            existing_ids.add(data["transaction_id"])
            to_create.append(
                Transaction(
                    transaction_id=data["transaction_id"],
                    entity=entities[data["entity_name"]],
                    transaction_date=data["transaction_date"],
                    due_date=data["due_date"],
                    amount=data["amount"],
                    currency=data["currency"],
                    direction=data["direction"],
                    settlement_status=data["settlement_status"],
                    original_amount=data["original_amount"],
                    origin_currency=data["origin_currency"],
                    destination_currency=data["destination_currency"],
                    fx_rate=data["fx_rate"],
                    counterparty=data["counterparty"],
                    product_type=data["product_type"],
                    category=data["category"],
                    department=data["department"],
                    frequency=data["frequency"],
                    is_recurring=data["is_recurring"],
                    is_cross_border=data["is_cross_border"],
                    interest_rate=data["interest_rate"],
                    maturity_date=data["maturity_date"],
                )
            )
        Transaction.objects.bulk_create(to_create, batch_size=2000)
        stats["new_transactions"] = len(to_create)

        if backfill:
            objs = list(Transaction.objects.filter(transaction_id__in=backfill.keys()))
            for obj in objs:
                data = backfill[obj.transaction_id]
                for field in ML_FIELDS:
                    setattr(obj, field, data[field])
            Transaction.objects.bulk_update(objs, ML_FIELDS, batch_size=2000)
        stats["ml_fields_backfilled"] = len(backfill)

    return stats


def ensure_default_thresholds():
    """
    Create a LiquidityThreshold for every (entity, currency) that has
    transactions but no threshold yet. Existing (admin-edited) values are kept.
    """
    pairs = (
        Transaction.objects.values_list("entity_id", "currency").distinct()
    )
    existing = set(
        LiquidityThreshold.objects.values_list("entity_id", "currency")
    )
    created = [
        LiquidityThreshold(
            entity_id=entity_id,
            currency=currency,
            minimum_balance=default_threshold(currency),
        )
        for entity_id, currency in pairs
        if (entity_id, currency) not in existing
    ]
    LiquidityThreshold.objects.bulk_create(created)
    return len(created)


def _daily_flows():
    return (
        Transaction.objects
        .filter(settlement_status="settled")
        .values("entity_id", "transaction_date", "currency")
        .annotate(
            inflow=Sum("amount", filter=Q(direction="inflow")),
            outflow=Sum("amount", filter=Q(direction="outflow")),
        )
        .order_by("entity_id", "currency", "transaction_date")
    )


def compute_opening_balances(daily_flows=None):
    """
    The dataset has no bank balances, only flows. Opening balance B0 per
    (entity, currency) is calibrated so the lowest historical closing
    balance lands exactly on the minimum threshold:

        B0 = T + ceil(max(0, -min cumulative net flow) / 1000) * 1000

    Entities that never draw down start at their threshold.
    """
    flows = list(daily_flows if daily_flows is not None else _daily_flows())
    thresholds = {
        (t.entity_id, t.currency): t.minimum_balance
        for t in LiquidityThreshold.objects.all()
    }
    running = defaultdict(lambda: Decimal("0"))
    lowest = defaultdict(lambda: Decimal("0"))
    for flow in flows:
        key = (flow["entity_id"], flow["currency"])
        running[key] += (flow["inflow"] or 0) - (flow["outflow"] or 0)
        lowest[key] = min(lowest[key], running[key])

    opening = {}
    for key, low in lowest.items():
        threshold = thresholds.get(key, default_threshold(key[1]))
        drawdown = max(Decimal("0"), -low)
        opening[key] = threshold + Decimal(math.ceil(drawdown / 1000) * 1000)
    return opening


def rebuild_cash_positions(opening_balances=None):
    """
    Rebuild daily cash flows from settled transactions only.

    closing_balance = opening balance (see compute_opening_balances) plus
    cumulative net movement. The data has no verified bank balance, so the
    opening balance is a calibrated assumption, not a bank figure.
    """
    daily_flows = list(_daily_flows())
    if opening_balances is None:
        opening_balances = compute_opening_balances(daily_flows)

    running_totals = defaultdict(lambda: Decimal("0"))
    for key, value in opening_balances.items():
        running_totals[key] = Decimal(value)
    positions = []

    for flow in daily_flows:
        key = (flow["entity_id"], flow["currency"])
        inflow = flow["inflow"] or Decimal("0")
        outflow = flow["outflow"] or Decimal("0")
        net_flow = inflow - outflow
        running_totals[key] += net_flow

        positions.append(
            CashPosition(
                entity_id=flow["entity_id"],
                date=flow["transaction_date"],
                currency=flow["currency"],
                closing_balance=running_totals[key],
                cash_flow=net_flow,
                daily_inflow=inflow,
                daily_outflow=outflow,
                net_flow=net_flow,
            )
        )

    with transaction.atomic():
        CashPosition.objects.all().delete()
        CashPosition.objects.bulk_create(positions, batch_size=1000)

    return {
        "positions_created": len(positions),
        "settled_transactions_used": Transaction.objects.filter(
            settlement_status="settled"
        ).count(),
        "opening_balances": {
            f"{entity_id}:{currency}": float(value)
            for (entity_id, currency), value in opening_balances.items()
        },
    }


def ingest_csv(file_path):
    """
    Full ingestion used by the upload endpoint and the management command:
    validate + import, seed missing thresholds, rebuild cash positions.
    The forecast (ML Script 2) is triggered separately by the caller.
    """
    stats = import_csv_dataset(file_path, dry_run=False)
    stats["thresholds_created"] = ensure_default_thresholds()
    positions = rebuild_cash_positions()
    stats["positions_created"] = positions["positions_created"]
    return stats
