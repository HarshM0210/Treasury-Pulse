
import csv
from collections import Counter

from treasury.ingestion import (
    validate_csv_headers,
    normalize_transaction,
)

CSV_PATH = "UC5 - sample_transactions v3.csv"

counts = Counter()
seen_ids = set()
duplicate_ids = []
currency_mismatches = []
entities = set()
countries = set()

with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    validate_csv_headers(reader.fieldnames)

    for line_number, row in enumerate(reader, start=2):
        try:
            transaction = normalize_transaction(row)
            counts["valid"] += 1
            counts[transaction["settlement_status"]] += 1

            transaction_id = transaction["transaction_id"]
            if transaction_id in seen_ids and len(duplicate_ids) < 10:
                duplicate_ids.append(transaction_id)
            seen_ids.add(transaction_id)

            source_currency = (row.get("currency") or "").strip().upper()
            if source_currency != transaction["currency"]:
                if len(currency_mismatches) < 10:
                    currency_mismatches.append(
                        (
                            line_number,
                            transaction_id,
                            source_currency,
                            transaction["currency"],
                        )
                    )

            entities.add(transaction["entity_name"])
            countries.add(transaction["country"])

        except (ValueError, TypeError) as exc:
            counts["invalid"] += 1
            print(f"Line {line_number}: {exc}")

print("Rows validated:", counts["valid"])
print("Settled:", counts["settled"])
print("Failed:", counts["failed"])
print("Unique transaction IDs:", len(seen_ids))
print("Unique entities:", len(entities))
print("Countries as written:", sorted(countries))
print("Duplicate IDs (up to 10):", duplicate_ids)
print("Currency mismatches (up to 10):", currency_mismatches)
