"""

SCRIPT 2 — build the forecasting model and store 30-day forecasts.


    result = run()              # skips if forecasts for the current data already exist

    result = run(force=True)    # refit regardless


One Prophet model per entity:

    target     y          daily settled net cash flow (by transaction_date),

                          clipped at p1/p99; the clipped mean is added back

    regressors sched_in   Σ inflow amount × (1 − R(t)) expected to land that day

               sched_out  Σ outflow amount expected to land that day (negative)

               month_end  1 in the last 3 days of a month

               quarter_end 1 in the last 5 days of a quarter

    settings   flat trend, weekly + monthly (30.5d) + quarterly (91.25d) seasonality


"Expected to land that day" spreads each transaction's due date over the

empirical (actual − due) lag distribution of its payment frequency. For the

forecast window only transactions still pending at as_of are used.


Balance = position at as_of + cumulative predicted flow. The confidence band

comes from Prophet's predictive samples, accumulated path by path.


Writes: Forecast rows (one per entity per day, latest run only) and Alerts.

"""

from __future__ import annotations


import logging

import threading

import time

from decimal import Decimal


import numpy as np

import pandas as pd

from django.conf import settings

from django.db import transaction

from django.utils import timezone


from treasury.models import Alert, Forecast


from . import rules

from .script1_prepare import Prepared, current_fingerprint, expected_flows, lag_distributions, make_run_id, prepare


log = logging.getLogger("ml")

_run_lock = threading.Lock()


# ─── features ──────────────────────────────────────────────────────────


def _calendar(frame):

    ds = frame["ds"]

    frame["month_end"] = ((ds.dt.days_in_month - ds.dt.day) < 3).astype(float)

    quarter_end = ds + pd.offsets.QuarterEnd(0)

    frame["quarter_end"] = ((quarter_end - ds).dt.days < 5).astype(float)

    return frame


def build_frames(prep: Prepared, entity_id: int, horizon: int):
    """Construct Prophet target and scheduled-payment regressors as of prep.as_of.

    The source includes eventual outcomes for historical demo/backtest periods.
    Future ACTUAL settlement outcomes are not used to decide what is pending.
    Assumption: recurring/monthly/quarterly rows were known in the ERP schedule
    at the forecast cutoff; the provided data has no schedule-created timestamp.
    """
    tx = prep.tx.loc[prep.tx.entity_id.eq(entity_id)].copy()
    cutoff = pd.Timestamp(prep.as_of).normalize()

    # Which transactions the ERP is assumed to know before they settle.
    # Default: every transaction with a due date (invoices/payables are booked
    # before they are paid). ML_SCHEDULED_ONLY=True restricts this to recurring /
    # monthly / quarterly flows; in backtests that raised RMSE by ~30% because
    # ~36% of known cash movements were left to the statistical part.
    if getattr(settings, "ML_SCHEDULED_ONLY", False):
        is_scheduled = tx["is_recurring"].eq(True) | tx["frequency"].isin(("monthly", "quarterly"))
    else:
        is_scheduled = tx["due_date"].notna()

    tx["w_in"] = np.where(tx.direction.eq("inflow"), tx.amount * (1 - tx.R), 0.0)
    tx["w_out"] = np.where(tx.direction.eq("outflow"), -tx.amount, 0.0)

    hist_days = pd.date_range(prep.data_start, cutoff, freq="D")
    fut_days = pd.date_range(cutoff + pd.Timedelta(days=1), periods=horizon, freq="D")

    # Observed target: ONLY settled transactions whose actual date <= cutoff.
    settled_history = tx.loc[tx.settled & tx.transaction_date.le(cutoff)]
    y = (settled_history.groupby("transaction_date")["signed"].sum()
         .reindex(hist_days, fill_value=0.0))

    # The preparation script's lag_pmf currently also includes failed rows.
    # Recompute using actual settled outcomes available at THIS cutoff.
    lag_pmf = lag_distributions(settled_history)

    # Restrict historical scheduled features to schedules due by the cutoff.
    # Transactions with future actual dates are not used as observed y.
    scheduled_hist = tx.loc[is_scheduled & tx.due_date.le(cutoff)]
    inflows = scheduled_hist.loc[scheduled_hist.direction.eq("inflow")]
    outflows = scheduled_hist.loc[scheduled_hist.direction.eq("outflow")]
    train = pd.DataFrame({
        "ds": hist_days,
        "y": y.to_numpy(float),
        "sched_in": expected_flows(inflows, "w_in", lag_pmf, hist_days),
        "sched_out": expected_flows(outflows, "w_out", lag_pmf, hist_days),
    })

    # A past record can only be excluded if it had already been settled/failed
    # on or before the cutoff. Never filter on "transaction_date > cutoff" alone;
    # that wrongly excludes known future-due rows paid early and is outcome-driven.
    finished_by_cutoff = (
        (tx["settled"] | tx["failed"])
        & tx["transaction_date"].le(cutoff)
    )
    pending = tx.loc[is_scheduled & ~finished_by_cutoff]
    future = pd.DataFrame({
        "ds": fut_days,
        "sched_in": expected_flows(
            pending.loc[pending.direction.eq("inflow")],
            "w_in", lag_pmf, fut_days, after=cutoff,
        ),
        "sched_out": expected_flows(
            pending.loc[pending.direction.eq("outflow")],
            "w_out", lag_pmf, fut_days, after=cutoff,
        ),
    })
    return _calendar(train), _calendar(future)


# ─── model ─────────────────────────────────────────────────────────────


REGRESSORS = ["sched_in", "sched_out", "month_end", "quarter_end"]


def fit_predict(train: pd.DataFrame, future: pd.DataFrame, n_samples: int, ci: float):
    """Fit Prophet ONLY; return expected daily flows and predictive samples.

    scheduled = Prophet's learned regressor contribution, NOT the raw expected
    sum of known payments. The dashboard should label it accordingly.
    """
    if n_samples < 0:
        raise ValueError("n_samples must be >= 0")
    if not 0 < ci < 1:
        raise ValueError("ci must lie strictly between 0 and 1")
    if len(train) < 60:
        raise ValueError("At least 60 daily training observations are required")

    y = train["y"].astype(float)
    lo, hi = y.quantile(0.01), y.quantile(0.99)
    clipped = y.clip(lo, hi)
    tail_adj = float(y.mean() - clipped.mean())
    fit_frame = train.assign(y=clipped)

    try:
        from prophet import Prophet
        from prophet.utilities import regressor_coefficients
    except ImportError as exc:
        raise RuntimeError(
            "Prophet is required. Install it with: python -m pip install prophet"
        ) from exc

    model = Prophet(
        growth="flat",
        yearly_seasonality=False,
        weekly_seasonality=True,
        daily_seasonality=False,
        seasonality_mode="additive",
        interval_width=ci,
        uncertainty_samples=n_samples,
    )
    model.add_seasonality(name="monthly", period=30.5, fourier_order=5)
    model.add_seasonality(name="quarterly", period=91.25, fourier_order=3)

    # Constant regressors cannot provide a meaningful learned relationship.
    active_regressors = []
    for regressor in REGRESSORS:
        if fit_frame[regressor].nunique(dropna=True) > 1:
            model.add_regressor(regressor)
            active_regressors.append(regressor)

    model.fit(fit_frame)
    prediction = model.predict(future)
    mean = prediction["yhat"].to_numpy(float) + tail_adj

    # Bias backtests request zero samples to avoid unnecessary computation.
    if n_samples > 0:
        samples = np.asarray(model.predictive_samples(future)["yhat"], dtype=float) + tail_adj
    else:
        samples = np.empty((len(future), 0), dtype=float)

    coef = {regressor: 0.0 for regressor in REGRESSORS}
    if active_regressors:
        rows = regressor_coefficients(model)
        for record in rows.itertuples(index=False):
            coef[record.regressor] = float(record.coef)

    scheduled_contribution = (
        future["sched_in"].to_numpy(float) * coef["sched_in"]
        + future["sched_out"].to_numpy(float) * coef["sched_out"]
    )
    return {
        "mean": mean,
        "samples": samples,
        "scheduled": scheduled_contribution,
        "method": "prophet",
        "coef": coef,
    }


def bias_vector(prep: Prepared, entity_id: int, horizon: int,
                n_origins=3, step=15, origin_cache=None):
    """Mean daily forecast error across earlier cutoffs, using cutoff-safe inputs.

    Each backtest origin MUST rebuild its risk model and payment lag distribution.
    """
    errors = []
    for k in range(n_origins):
        origin = prep.as_of - pd.Timedelta(days=horizon + k * step)
        if (origin - prep.data_start).days < 90:
            break

        # Re-running preparation at the historical origin is essential.
        # Merely changing the as_of field would leak later risk estimates.
        if origin_cache is not None and origin in origin_cache:
            shifted = origin_cache[origin]
        else:
            shifted = prepare(as_of=origin)
            if origin_cache is not None:
                origin_cache[origin] = shifted

        train, future = build_frames(shifted, entity_id, horizon)
        out = fit_predict(train, future, n_samples=0, ci=settings.ML_CI_LEVEL)

        # Use the EXISTING daily cash-position snapshots to evaluate errors.
        # Differencing successive closing balances yields observed daily net flow.
        snapshot_dates = pd.DatetimeIndex([origin]).append(
            pd.DatetimeIndex(future["ds"])
        )
        snapshot_positions = prep.positions[entity_id].reindex(snapshot_dates)
        if snapshot_positions.isna().any():
            raise ValueError(
                f"Existing position snapshots do not cover origin {origin} "
                f"and its full {horizon}-day forecast for entity {entity_id}"
            )
        actual = np.diff(snapshot_positions.to_numpy(dtype=float))
        errors.append(out["mean"] - actual)

    return np.mean(errors, axis=0) if errors else np.zeros(horizon)


def forecast_entity(prep: Prepared, entity_id: int, horizon=None,
                    calibrate=None, origin_cache=None):
    horizon = horizon or settings.ML_HORIZON_DAYS
    ci = settings.ML_CI_LEVEL
    calibrate = settings.ML_BIAS_CALIBRATION if calibrate is None else calibrate
    samples_count = settings.ML_UNCERTAINTY_SAMPLES
    if not 1 <= horizon <= 365:
        raise ValueError("horizon must be between 1 and 365 days")
    if samples_count <= 0:
        raise ValueError("ML_UNCERTAINTY_SAMPLES must be positive")

    entity = prep.entity(entity_id)
    threshold = float(entity.threshold)
    if threshold <= 0:
        raise ValueError("Liquidity threshold must be positive")

    train, future = build_frames(prep, entity_id, horizon)
    out = fit_predict(train, future, samples_count, ci)
    bias = (bias_vector(prep, entity_id, horizon, origin_cache=origin_cache)
            if calibrate else np.zeros(horizon))

    # Use the existing balance from Script 1; do NOT synthesize any new data.
    opening = float(prep.positions[entity_id].get(prep.as_of, np.nan))
    if not np.isfinite(opening):
        raise ValueError(f"No valid existing opening balance for entity {entity_id} at {prep.as_of}")

    flows = out["mean"] - bias
    balance = opening + np.cumsum(flows)
    paths = opening + np.cumsum(out["samples"] - bias[:, None], axis=0)
    q = (1 - ci) / 2
    lower = np.percentile(paths, 100 * q, axis=1)
    upper = np.percentile(paths, 100 * (1 - q), axis=1)
    breach_p = (paths < threshold).mean(axis=1)

    frame = pd.DataFrame({
        "forecast_date": future["ds"].dt.date,
        "predicted_balance": balance,
        "lower_bound": lower,
        "upper_bound": upper,
        # NB: This is the Prophet regressor contribution, not raw payments.
        "scheduled_net": out["scheduled"],
        "predicted_net": flows - out["scheduled"],
        "liquidity_gap": balance - threshold,
        "risk_level": [rules.classify(b, threshold) for b in balance],
        "breach_probability": breach_p,
    })
    return frame, {
        "method": out["method"],
        "opening_balance": opening,
        "coef": out["coef"],
        "bias_applied": bool(np.any(bias)),
    }


# ─── persistence ───────────────────────────────────────────────────────


def _dec(x):

    return Decimal(str(round(float(x), 4)))


def store_forecast(entity_id, currency, frame, run_id):

    rows = [

        Forecast(

            entity_id=entity_id, currency=currency, forecast_run_id=run_id,

            forecast_date=r.forecast_date, predicted_balance=_dec(r.predicted_balance),

            lower_bound=_dec(r.lower_bound), upper_bound=_dec(r.upper_bound),

            scheduled_net=_dec(r.scheduled_net), predicted_net=_dec(r.predicted_net),

            liquidity_gap=_dec(r.liquidity_gap), risk_level=r.risk_level,

        )

        for r in frame.itertuples()

    ]

    with transaction.atomic():

        Forecast.objects.filter(entity_id=entity_id).delete()      # keep only the latest run

        Forecast.objects.bulk_create(rows)


def sync_alert(entity_id, currency, threshold, frame, run_id, opening):

    """One active alert per entity, reflecting the worst level in the horizon.


    - worst level is WARNING/CRITICAL/EMERGENCY → create or update the alert

      (re-opened if it got worse after being acknowledged)

    - otherwise → auto-resolve any active alert

    """

    levels = list(frame["risk_level"])

    actual_level = rules.classify(opening, threshold)

    worst = rules.worst(levels + [actual_level])

    active = Alert.objects.filter(entity_id=entity_id, status__in=["OPEN", "ACKNOWLEDGED"]).first()

    now = timezone.now()


    if worst not in rules.ALERT_LEVELS:

        if active:

            active.status, active.resolved_at, active.resolved_by = "RESOLVED", now, "system"

            active.title = active.title or "Condition cleared"

            active.save()

        return None


    if actual_level == worst:

        low = {"forecast_date": None, "predicted_balance": opening, "liquidity_gap": opening - threshold,

               "breach_probability": float(opening < threshold)}

        source = "ACTUAL"

    else:

        # Date, gap, balance and probability refer to the SAME breach day.
        first = frame.loc[frame["risk_level"].eq(worst)].iloc[0]
        low = first.to_dict()
        low["first_date"] = first["forecast_date"]
        source = "FORECAST"


    first_date = low.get("first_date", low["forecast_date"])

    when = f" from {first_date}" if first_date else " today"

    # The alert describes the first breach day; also report the true low point.
    lowest = ""
    if source == "FORECAST":
        trough = frame.loc[frame["predicted_balance"].idxmin()]
        lowest = (f" (projected {low['predicted_balance']:,.0f} {currency} that day; "
                  f"lowest {trough['predicted_balance']:,.0f} on {trough['forecast_date']})")

    title = {

        "EMERGENCY": f"Projected below threshold{when}{lowest}",

        "CRITICAL": f"Projected within 5% of threshold{when}{lowest}",

        "WARNING": f"Projected within 10% of threshold{when}{lowest}",

    }[worst]

    fields = dict(

        severity=worst, liquidity_gap=_dec(low["liquidity_gap"]), currency=currency,

        projected_balance=_dec(low["predicted_balance"]), threshold=_dec(threshold),

        metric_date=first_date, breach_probability=float(low["breach_probability"]),

        title=title, source=source, forecast_run_id=run_id,

    )

    if active:

        got_worse = rules.SEVERITY[worst] < rules.SEVERITY.get(active.severity, 99)

        for k, v in fields.items():

            setattr(active, k, v)

        if got_worse:

            active.status = "OPEN"

        active.save()

        return active

    return Alert.objects.create(entity_id=entity_id, status="OPEN", **fields)


# ─── entry points ──────────────────────────────────────────────────────


def latest_run_id():

    return Forecast.objects.order_by("-id").values_list("forecast_run_id", flat=True).first()


def is_up_to_date(as_of=None):

    resolved, fingerprint = current_fingerprint(as_of)

    if fingerprint is None:

        return False, None

    run_id = make_run_id(resolved, fingerprint)

    from treasury.models import Entity

    expected = Entity.objects.filter(transactions__isnull=False).distinct().count()

    from django.db.models import Count
    counts = list(
        Forecast.objects.filter(forecast_run_id=run_id)
        .values("entity_id")
        .annotate(total=Count("id"))
        .values_list("total", flat=True)
    )
    complete = len(counts) == expected and all(
        count == settings.ML_HORIZON_DAYS for count in counts
    )
    return complete and expected > 0, run_id


def run(force=False, as_of=None, calibrate=None, entity_ids=None):

    """Script 2 entry point. Thread-safe; concurrent callers wait, then skip."""

    with _run_lock:

        fresh, run_id = is_up_to_date(as_of)

        if fresh and not force and not entity_ids:

            return {"status": "up_to_date", "forecast_run_id": run_id}


        t0 = time.perf_counter()

        prep = prepare(as_of)

        summary = {}
        origin_cache = {}  # reuse historical preparation across entities

        for eid, ent in prep.entities.iterrows():

            if entity_ids and int(eid) not in entity_ids:

                continue

            if eid not in prep.positions or prep.tx[prep.tx.entity_id == eid].empty:

                continue

            t1 = time.perf_counter()

            frame, meta = forecast_entity(
                prep, int(eid), calibrate=calibrate, origin_cache=origin_cache,
            )
            # Save prediction and associated alert together or roll back both.
            with transaction.atomic():
                store_forecast(int(eid), ent.currency, frame, prep.run_id)
                alert = sync_alert(
                    int(eid), ent.currency, float(ent.threshold),
                    frame, prep.run_id, meta["opening_balance"],
                )

            summary[ent["name"]] = {

                "entity_id": int(eid),

                "worst_level": rules.worst(frame.risk_level),

                "min_balance": float(frame.predicted_balance.min()),

                "alert": alert.severity if alert else None,

                "method": meta["method"],

                "seconds": round(time.perf_counter() - t1, 2),

            }

        elapsed = round(time.perf_counter() - t0, 1)

        log.info("Script2: run %s in %ss", prep.run_id, elapsed)

        return {"status": "completed", "forecast_run_id": prep.run_id, "as_of": str(prep.as_of.date()),

                "elapsed_seconds": elapsed, "entities": summary, "risk_model": prep.risk.as_dict()}


def _breach_from_band(f, threshold):

    """P(balance < threshold) assuming a normal band: σ = (upper − lower) / (2·z)."""

    from statistics import NormalDist

    if f.lower_bound is None or f.upper_bound is None:

        return float(float(f.predicted_balance) < threshold)

    z = NormalDist().inv_cdf(0.5 + settings.ML_CI_LEVEL / 2)

    sigma = (float(f.upper_bound) - float(f.lower_bound)) / (2 * z)

    if sigma <= 0:

        return float(float(f.predicted_balance) < threshold)

    return NormalDist().cdf((threshold - float(f.predicted_balance)) / sigma)


def reclassify(entity_ids=None):

    """After a threshold change: recompute gap, level and alerts without refitting."""

    from .script1_prepare import invalidate_cache

    from treasury.models import LiquidityThreshold


    invalidate_cache()

    qs = Forecast.objects.all()

    if entity_ids:

        qs = qs.filter(entity_id__in=entity_ids)

    thresholds = {(t.entity_id, t.currency): float(t.minimum_balance) for t in LiquidityThreshold.objects.all()}

    by_entity = {}

    for f in qs:

        by_entity.setdefault((f.entity_id, f.currency), []).append(f)

    for (eid, ccy), rows in by_entity.items():

        threshold = thresholds.get((eid, ccy))

        if threshold is None:

            continue

        for f in rows:

            f.liquidity_gap = _dec(float(f.predicted_balance) - threshold)

            f.risk_level = rules.classify(f.predicted_balance, threshold)

        Forecast.objects.bulk_update(rows, ["liquidity_gap", "risk_level"])

        rows.sort(key=lambda f: f.forecast_date)

        frame = pd.DataFrame({

            "forecast_date": [f.forecast_date for f in rows],

            "predicted_balance": [float(f.predicted_balance) for f in rows],

            "liquidity_gap": [float(f.liquidity_gap) for f in rows],

            "risk_level": [f.risk_level for f in rows],

            "breach_probability": [_breach_from_band(f, threshold) for f in rows],

        })

        from treasury.models import CashPosition

        last = CashPosition.objects.filter(entity_id=eid, currency=ccy,

                                           date__lt=rows[0].forecast_date).order_by("-date").first()

        opening = float(last.closing_balance) if last else float(rows[0].predicted_balance)

        sync_alert(eid, ccy, threshold, frame, rows[0].forecast_run_id, opening)

    return len(by_entity)
