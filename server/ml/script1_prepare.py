"""
SCRIPT 1 — fetch, clean and transform the data the forecasting model needs.

    prep = prepare()            # as_of from settings.ML_AS_OF
    prep = prepare("2025-11-28")

Returns a Prepared object holding:
    tx          one row per transaction, cleaned, with risk R(t)
    entities    one row per entity: currency, threshold, region …
    positions   entity_id -> daily closing balance (gap-filled)
    lag_pmf     frequency -> distribution of (actual − due) days
    risk        fitted counterparty-risk model
    usd_rate    currency -> USD per 1 unit (derived from the data's FX rates)
    as_of, fingerprint, health report
"""
from __future__ import annotations

import hashlib
import logging
import math
import threading
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from django.conf import settings
from django.db.models import Count, Max, Q, Sum

from treasury.defaults import default_threshold
from treasury.models import CashPosition, Entity, LiquidityThreshold, Transaction

from .risk import RiskModel, apply_risk, fit_risk

log = logging.getLogger("ml")

MODEL_VERSION = "prophet-reg-v1"
UNKNOWN = "unknown"

TX_FIELDS = [
    "id", "transaction_id", "entity_id", "transaction_date", "due_date", "amount",
    "currency", "direction", "settlement_status", "counterparty", "product_type",
    "category", "department", "frequency", "is_recurring", "is_cross_border",
    "interest_rate", "maturity_date", "origin_currency", "destination_currency", "fx_rate",
]


@dataclass
class Prepared:
    as_of: pd.Timestamp
    data_start: pd.Timestamp
    data_end: pd.Timestamp
    tx: pd.DataFrame
    entities: pd.DataFrame
    positions: dict
    lag_pmf: dict
    risk: RiskModel
    usd_rate: dict
    fingerprint: str
    health: dict = field(default_factory=dict)

    @property
    def run_id(self):
        return make_run_id(self.as_of, self.fingerprint)

    def entity(self, entity_id):
        return self.entities.loc[int(entity_id)]

    def pending(self, entity_id):
        """Transactions known to the ERP but not yet settled at as_of."""
        t = self.tx
        return t[(t.entity_id == int(entity_id)) & (t.transaction_date > self.as_of)]


# ─── fingerprint / as_of ────────────────────────────────────────────────

def make_run_id(as_of, fingerprint):
    return f"{pd.Timestamp(as_of):%Y-%m-%d}_{fingerprint[:10]}"


def parse_run_id(run_id):
    try:
        return pd.Timestamp(run_id.split("_")[0])
    except (ValueError, AttributeError, IndexError):
        return None


def data_signature():
    """Cheap DB aggregate that changes whenever the transaction data changes."""
    agg = Transaction.objects.aggregate(
        n=Count("id"), max_id=Max("id"), max_date=Max("transaction_date"), total=Sum("amount"),
        enriched=Count("id", filter=~Q(counterparty="")),
    )
    return agg


def resolve_as_of(max_date, as_of=None):
    value = as_of or getattr(settings, "ML_AS_OF", "auto")
    horizon = getattr(settings, "ML_HORIZON_DAYS", 30)
    if isinstance(value, str) and value.lower() == "auto":
        return pd.Timestamp(max_date) - pd.Timedelta(days=horizon)
    if isinstance(value, str) and value.lower() == "latest":
        return pd.Timestamp(max_date)
    return pd.Timestamp(value).normalize()


def current_fingerprint(as_of=None):
    """(as_of, fingerprint) for the data currently in the DB, without loading it."""
    sig = data_signature()
    if not sig["n"]:
        return None, None
    resolved = resolve_as_of(sig["max_date"], as_of)
    raw = f"{MODEL_VERSION}|{sig['n']}|{sig['max_id']}|{sig['max_date']}|{sig['total']}|{sig['enriched']}|{resolved.date()}"
    return resolved, hashlib.md5(raw.encode()).hexdigest()


# ─── cleaning ───────────────────────────────────────────────────────────

def fetch_transactions():
    return pd.DataFrame.from_records(Transaction.objects.values(*TX_FIELDS).iterator(chunk_size=5000),
                                     columns=TX_FIELDS)


def clean_transactions(raw: pd.DataFrame):
    """Types, missing values, duplicates, derived fields. Returns (frame, health)."""
    health = {"rows_in": int(len(raw)), "issues": []}

    def issue(code, count, message):
        if count:
            health["issues"].append({"code": code, "count": int(count), "message": message})

    df = raw.copy()
    df["transaction_date"] = pd.to_datetime(df["transaction_date"], errors="coerce")
    df["due_date"] = pd.to_datetime(df["due_date"], errors="coerce")
    df["maturity_date"] = pd.to_datetime(df["maturity_date"], errors="coerce")
    for col in ("amount", "interest_rate", "fx_rate"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)
    for col in ("direction", "settlement_status", "frequency", "product_type", "category", "department"):
        df[col] = df[col].fillna("").astype(str).str.strip().str.lower()
    df["counterparty"] = df["counterparty"].fillna("").astype(str).str.strip()
    df["currency"] = df["currency"].fillna("").astype(str).str.upper()

    bad = df["transaction_date"].isna() | df["amount"].isna() | ~df["direction"].isin(["inflow", "outflow"])
    issue("UNUSABLE_ROWS", bad.sum(), "Rows without date, amount or a valid direction were ignored")
    df = df[~bad]

    neg = df["amount"] < 0
    issue("NEGATIVE_AMOUNT", neg.sum(), "Negative amounts made positive; direction is the source of truth")
    df.loc[neg, "amount"] = df.loc[neg, "amount"].abs()

    dup = df.duplicated("transaction_id")
    issue("DUPLICATE_ID", dup.sum(), "Duplicate transaction ids ignored")
    df = df[~dup]

    no_due = df["due_date"].isna()
    issue("MISSING_DUE_DATE", no_due.sum(), "Missing due date set to the transaction date")
    df.loc[no_due, "due_date"] = df.loc[no_due, "transaction_date"]

    for col, msg in (("counterparty", "Missing counterparty: treated as one 'unknown' counterparty"),
                     ("frequency", "Missing frequency: timing learned from all transactions")):
        missing = df[col].eq("")
        issue(f"MISSING_{col.upper()}", missing.sum(), msg)
        df.loc[missing, col] = UNKNOWN

    df["is_recurring"] = df["is_recurring"].fillna(False).astype(bool)
    df["is_cross_border"] = df["is_cross_border"].fillna(
        df["origin_currency"].fillna("") != df["destination_currency"].fillna("")
    ).astype(bool)
    df["failed"] = df["settlement_status"].eq("failed")
    df["settled"] = df["settlement_status"].eq("settled")
    df["signed"] = np.where(df["direction"].eq("inflow"), 1.0, -1.0) * df["amount"]
    df["lag_days"] = (df["transaction_date"] - df["due_date"]).dt.days
    df["entity_id"] = df["entity_id"].astype(int)

    health.update({
        "rows_used": int(len(df)),
        "rows_failed": int(df["failed"].sum()),
        "rows_cross_border": int(df["is_cross_border"].sum()),
        "date_min": str(df["transaction_date"].min().date()) if len(df) else None,
        "date_max": str(df["transaction_date"].max().date()) if len(df) else None,
    })
    return df.reset_index(drop=True), health


# ─── transforms ─────────────────────────────────────────────────────────

def lag_distributions(history: pd.DataFrame):
    """frequency -> P(actual − due = k days), learned from settled history."""
    pmf = {f: g.value_counts(normalize=True).sort_index()
           for f, g in history.groupby("frequency")["lag_days"]}
    pmf["__all__"] = history["lag_days"].value_counts(normalize=True).sort_index() \
        if len(history) else pd.Series([1.0], index=[0])
    return pmf


def usd_rates(tx: pd.DataFrame):
    """USD value of 1 unit of each currency, from the dataset's own fx_rate.

    fx_rate = units of origin currency per 1 unit of destination currency.
    """
    xb = tx[tx["is_cross_border"] & tx["fx_rate"].gt(0)]
    to_usd = xb[xb["destination_currency"] == "USD"].groupby("origin_currency")["fx_rate"].median()
    from_usd = xb[xb["origin_currency"] == "USD"].groupby("destination_currency")["fx_rate"].median()
    rates = {"USD": 1.0}
    for ccy in set(tx["currency"]) | set(to_usd.index) | set(from_usd.index):
        if ccy == "USD" or not ccy:
            continue
        if ccy in to_usd.index:
            rates[ccy] = float(1.0 / to_usd[ccy])
        elif ccy in from_usd.index:
            rates[ccy] = float(from_usd[ccy])
    return rates


def load_entities(tx):
    ents = pd.DataFrame.from_records(Entity.objects.values("id", "name", "region", "country"))
    if ents.empty:
        return ents
    ents = ents.set_index("id")
    ccy = tx.groupby("entity_id")["currency"].agg(lambda s: s.mode().iat[0])
    ents["currency"] = ccy.reindex(ents.index).fillna("USD")
    thr = {(t.entity_id, t.currency): float(t.minimum_balance) for t in LiquidityThreshold.objects.all()}
    ents["threshold"] = [thr.get((i, c), float(default_threshold(c))) for i, c in zip(ents.index, ents.currency)]
    ents["code"] = ents["name"].str.replace(r"^[A-Z]+BANK_", "", regex=True)
    return ents


def load_positions(tx, entities, start, end):
    """Daily closing balance per entity from CASH_POSITION, forward-filled.

    Falls back to rebuilding from transactions (same opening-balance rule) if
    CASH_POSITION is empty."""
    days = pd.date_range(start, end, freq="D")
    rows = pd.DataFrame.from_records(CashPosition.objects.values("entity_id", "date", "closing_balance", "net_flow"))
    positions = {}
    for eid in entities.index:
        cp = rows[rows.entity_id == eid] if len(rows) else rows
        if len(cp):
            s = pd.Series(cp["closing_balance"].astype(float).values, index=pd.to_datetime(cp["date"])).sort_index()
            first_open = float(s.iloc[0] - float(cp.sort_values("date")["net_flow"].iloc[0]))
            s = s.reindex(days).ffill().fillna(first_open)
        else:
            settled = tx[(tx.entity_id == eid) & tx.settled]
            cum = settled.groupby("transaction_date")["signed"].sum().reindex(days, fill_value=0.0).cumsum()
            threshold = float(entities.at[eid, "threshold"])
            b0 = threshold + math.ceil(max(0.0, -cum.min()) / 1000.0) * 1000.0
            s = b0 + cum
        positions[int(eid)] = s
    return positions


# ─── expected scheduled flows (regressor builder, shared with Script 3) ─

def expected_flows(rows: pd.DataFrame, weight_col: str, pmf: dict, days: pd.DatetimeIndex,
                   date_col="due_date", after=None, shift_days=None):
    """Expected amount landing on each day of `days`.

    Each row's weight is spread over the lag distribution of its frequency
    (actual = due + lag). With `after`, rows are conditioned on settling
    strictly after that date (pending transactions); probability mass beyond
    `days` drops out. `shift_days` (Series aligned to rows) adds extra delay.
    """
    out = np.zeros(len(days))
    if rows.empty:
        return out
    day0 = days[0]
    n = len(days)
    rows = rows.assign(_w=rows[weight_col].astype(float),
                       _shift=(shift_days if shift_days is not None else 0))
    for freq, g in rows.groupby("frequency"):
        p = pmf.get(freq, pmf["__all__"])
        lags, probs = p.index.to_numpy(dtype=int), p.to_numpy(dtype=float)
        grouped = g.groupby([date_col, "_shift"])["_w"].sum()
        for (due, shift), w in grouped.items():
            settle = (pd.Timestamp(due) - day0).days + lags      # day offsets, before any delay
            pr = probs
            if after is not None:
                # Condition on "not settled by as_of" using the original timing,
                # then apply the extra delay.
                cut = (pd.Timestamp(after) - day0).days
                pr = np.where(settle > cut, probs, 0.0)
                total = pr.sum()
                if total <= 0:                       # overdue beyond anything seen → next day
                    settle, pr = np.array([cut + 1]), np.array([1.0])
                else:
                    pr = pr / total
            settle = settle + int(shift)
            inside = (settle >= 0) & (settle < n)
            np.add.at(out, settle[inside], w * pr[inside])
    return out


# ─── main entry point ──────────────────────────────────────────────────

_cache = {"key": None, "prep": None}
_cache_lock = threading.Lock()


def prepare(as_of=None, use_cache=True) -> Prepared:
    resolved, fingerprint = current_fingerprint(as_of)
    if fingerprint is None:
        raise ValueError("No transactions in the database. Import the CSV first.")
    key = (fingerprint, str(resolved.date()))
    with _cache_lock:
        if use_cache and _cache["key"] == key:
            return _cache["prep"]

    raw = fetch_transactions()
    tx, health = clean_transactions(raw)
    start, end = tx["transaction_date"].min(), tx["transaction_date"].max()

    history = tx[tx["transaction_date"] <= resolved]
    risk_model = fit_risk(history)
    tx = apply_risk(tx, risk_model)

    entities = load_entities(tx)
    prep = Prepared(
        as_of=resolved,
        data_start=start,
        data_end=end,
        tx=tx,
        entities=entities,
        positions=load_positions(tx, entities, start, end),
        lag_pmf=lag_distributions(history),
        risk=risk_model,
        usd_rate=usd_rates(tx),
        fingerprint=fingerprint,
        health=health,
    )
    log.info("Script1: %s rows, %s entities, as_of=%s, k_entity=%.0f k_pair=%.0f",
             len(tx), len(entities), resolved.date(), risk_model.k_entity, risk_model.k_pair)
    with _cache_lock:
        _cache.update(key=key, prep=prep)
    return prep


def invalidate_cache():
    with _cache_lock:
        _cache.update(key=None, prep=None)
