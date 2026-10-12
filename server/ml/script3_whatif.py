"""
SCRIPT 3 — what-if forecasts.

    result = run_what_if(entity_id, horizon=30, params={
        "payment_delay_days": 3,        # 0..5   delay pending outflows
        "capex_postpone_days": 14,      # 0..90  postpone pending capex outflows
        "fx_shock_pct": -10,            # ±5/10/15  change in entity currency vs USD/foreign
        "rate_shock_bps": 100,          # ±50/100/200  interest-rate shock
        "rating_shift": {"counterparty": "vendor_X", "new_rating": "D"},
    })

The model is not refitted. The scenario starts from the stored baseline
(Script 2) and adds the exact change in expected cash flows:

    Δ(d)               = scenario expected flows(d) − baseline expected flows(d)
    scenario_balance(d) = baseline_balance(d) + Σ Δ up to d

Expected flows use the same pending transactions, lag distributions and
counterparty risk R(t) as Script 2. Missing parameters default to "no
shock", so calling without parameters returns the baseline.
"""
from __future__ import annotations

import logging
from decimal import Decimal

import numpy as np
import pandas as pd
from django.conf import settings
from django.db import transaction

from treasury.models import Forecast, Scenario, ScenarioResult

from . import rules
from .script1_prepare import expected_flows, parse_run_id, prepare
from .script2_forecast import run as run_forecast

log = logging.getLogger("ml")

OVERDRAFT_RATE = 0.08          # annual, on balance below threshold
INVEST_RATE = 0.04             # annual, on deployable surplus
RATE_SENSITIVE = {"deposit", "loan_repayment", "revolving_credit", "standby_facility",
                  "commercial_paper", "hedge_settlement"}
DEFAULTS = {"payment_delay_days": 0, "capex_postpone_days": 0, "fx_shock_pct": 0.0,
            "rate_shock_bps": 0, "rating_shift": None}
LIMITS = {"payment_delay_days": (0, 5), "capex_postpone_days": (0, 90),
          "fx_shock_pct": (-50, 50), "rate_shock_bps": (-500, 500)}


def clean_params(params):
    p = dict(DEFAULTS)
    for key, (lo, hi) in LIMITS.items():
        value = (params or {}).get(key)
        if value in (None, ""):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a valid number") from None
        if not np.isfinite(value):
            raise ValueError(f"{key} must be a finite number")
        if not lo <= value <= hi:
            raise ValueError(f"{key} must be between {lo} and {hi}")
        # Day counts and basis-point shocks are whole-number controls.
        if key != "fx_shock_pct" and not value.is_integer():
            raise ValueError(f"{key} must be a whole number")
        p[key] = int(value) if key != "fx_shock_pct" else value
    shift = (params or {}).get("rating_shift")
    if shift and shift.get("counterparty") and shift.get("new_rating"):
        rating = str(shift["new_rating"]).upper()
        if rating not in rules.RATING_R:
            raise ValueError("new_rating must be A, B, C or D")
        p["rating_shift"] = {"counterparty": str(shift["counterparty"]), "new_rating": rating}
    return p


def scenario_type(p):
    active = [name for name, on in (
        ("PAYMENT_DELAY", p["payment_delay_days"]), ("CAPEX_POSTPONEMENT", p["capex_postpone_days"]),
        ("FX_SHOCK", p["fx_shock_pct"]), ("RATE_SHOCK", p["rate_shock_bps"]),
        ("RATING_SHIFT", p["rating_shift"])) if on]
    return active[0] if len(active) == 1 else ("BASELINE" if not active else "COMBINED")


def _baseline(entity_id, horizon):
    # Select one forecast run only; otherwise rows from multiple runs can be mixed.
    queryset = Forecast.objects.filter(entity_id=entity_id)
    latest_row = queryset.order_by("-id").first()

    if latest_row is None:
        run_forecast()
        queryset = Forecast.objects.filter(entity_id=entity_id)
        latest_row = queryset.order_by("-id").first()

    if latest_row is None:
        raise ValueError("No forecast available for this entity.")

    rows = list(
        queryset.filter(forecast_run_id=latest_row.forecast_run_id)
        .order_by("forecast_date")[:horizon]
    )
    if not rows:
        raise ValueError("No forecast available for this entity and forecast run.")
    return rows


def run_what_if(entity_id, horizon=None, params=None, persist=True):
    horizon = settings.ML_HORIZON_DAYS if horizon is None else int(horizon)
    if horizon <= 0:
        raise ValueError("horizon must be a positive integer")
    p = clean_params(params)
    base_rows = _baseline(int(entity_id), horizon)
    horizon = len(base_rows)
    run_id = base_rows[0].forecast_run_id
    prep = prepare(parse_run_id(run_id))
    ent = prep.entity(entity_id)
    threshold, currency = float(ent.threshold), ent.currency
    usd_rate = prep.usd_rate.get(currency, 1.0)
    days = pd.date_range(prep.as_of + pd.Timedelta(days=1), periods=horizon, freq="D")

    pend = prep.pending(entity_id).copy()
    inflow = pend.direction.eq("inflow")
    pend["w"] = np.where(inflow, pend.amount * (1 - pend.R), -pend.amount)
    pend["shift"] = 0
    scen = pend.copy()
    affected = pd.Series(False, index=pend.index)
    notes = []
    if pend.empty:
        # Every shock acts on transactions still pending after as_of. With as_of
        # on/after the last transaction date there are none, so scenario = baseline.
        notes.append(f"No pending transactions after the as-of date {prep.as_of.date()}: "
                     "the shocks have nothing to act on. Set ML_AS_OF earlier than the last "
                     "transaction date (default 'auto' = last date − 30 days).")

    # 1) Payment delay: pending outflows settle later
    if p["payment_delay_days"]:
        m = ~inflow
        scen.loc[m, "shift"] += p["payment_delay_days"]
        affected |= m
        notes.append(f"{int(m.sum())} pending outflows delayed by {p['payment_delay_days']} day(s)")

    # 2) Capex postponement: pending capex outflows move out
    if p["capex_postpone_days"]:
        m = (~inflow) & pend.product_type.eq("capex")
        scen.loc[m, "shift"] += p["capex_postpone_days"]
        affected |= m
        notes.append(f"{int(m.sum())} capex payments postponed by {p['capex_postpone_days']} day(s)")

    # 3) FX shock: foreign-denominated (cross-border) outflows cost less/more
    #    in entity currency; the USD value of the position is translated.
    fx = p["fx_shock_pct"] / 100.0
    fx_transaction = 0.0
    if fx:
        m = (~inflow) & pend.is_cross_border
        before = scen.loc[m, "w"].copy()
        scen.loc[m, "w"] = before / (1 + fx)
        fx_transaction = float((scen.loc[m, "w"] - before).sum())
        affected |= m
        notes.append(f"{int(m.sum())} cross-border payments revalued at {p['fx_shock_pct']:+g}%")

    # 4) Interest-rate shock on rate-bearing pending flows
    dr = p["rate_shock_bps"] / 10000.0
    interest_delta = 0.0
    extra = pend.iloc[0:0].copy()
    if dr:
        rated = pend[pend.interest_rate.notna() & (pend.interest_rate > 0)]
        coupons = rated[rated.product_type.eq("interest_payment")]
        # interest amount scales with the rate: amount × (r + Δ) / r
        scen.loc[coupons.index, "w"] = scen.loc[coupons.index, "w"] * (coupons.interest_rate + dr) / coupons.interest_rate
        principal = rated[rated.product_type.isin(RATE_SENSITIVE)].copy()
        accrual_days = (principal.due_date - prep.as_of).dt.days.clip(lower=0)
        sign = np.where(principal.direction.eq("inflow"), 1.0, -1.0)
        principal["w"] = sign * principal.amount * dr * accrual_days / 365.0
        principal["shift"] = 0
        extra = principal
        affected.loc[coupons.index] = True
        affected.loc[principal.index] = True
        notes.append(f"{len(coupons)} interest payments repriced, {len(principal)} rate-bearing flows accrue {p['rate_shock_bps']:+d} bps")

    # 5) Counterparty rating shift: inflows from that counterparty
    shift = p["rating_shift"]
    if shift:
        m = inflow & pend.counterparty.eq(shift["counterparty"])
        new_r = rules.RATING_R[shift["new_rating"]]
        scen.loc[m, "w"] = pend.loc[m, "amount"] * (1 - new_r)
        # current grade = counterparty-level score (same as the Counterparty Risk page)
        cp_rows = prep.tx[prep.tx.counterparty.eq(shift["counterparty"])]
        old_grade = rules.grade(float(cp_rows.R.mean())) if len(cp_rows) else "B"
        extra_delay = max(0, rules.RATING_DELAY_DAYS[shift["new_rating"]] - rules.RATING_DELAY_DAYS[old_grade])
        scen.loc[m, "shift"] += extra_delay
        affected |= m
        notes.append(f"{int(m.sum())} inflows from {shift['counterparty']} re-rated to {shift['new_rating']}")

    pmf = prep.lag_pmf
    base_flow = expected_flows(pend, "w", pmf, days, after=prep.as_of)
    scen_flow = expected_flows(scen, "w", pmf, days, after=prep.as_of, shift_days=scen["shift"])
    if len(extra):
        extra_flow = expected_flows(extra, "w", pmf, days, after=prep.as_of)
        scen_flow = scen_flow + extra_flow
        interest_delta += float(extra_flow.sum())
    if dr:
        coupon_idx = pend.index[pend.product_type.eq("interest_payment") & pend.interest_rate.notna()]
        interest_delta += float((expected_flows(scen.loc[coupon_idx], "w", pmf, days, after=prep.as_of)
                                 - expected_flows(pend.loc[coupon_idx], "w", pmf, days, after=prep.as_of)).sum())
    delta = scen_flow - base_flow
    cum = np.cumsum(delta)

    base = np.array([float(r.predicted_balance) for r in base_rows])
    lo = np.array([float(r.lower_bound if r.lower_bound is not None else r.predicted_balance) for r in base_rows])
    hi = np.array([float(r.upper_bound if r.upper_bound is not None else r.predicted_balance) for r in base_rows])
    scen_bal = base + cum
    translate = (1 + fx) if currency != "USD" else 1.0

    series = []
    for i, r in enumerate(base_rows):
        series.append({
            "date": str(r.forecast_date),
            "baseline": round(base[i], 2), "scenario": round(scen_bal[i], 2),
            "baseline_lower": round(lo[i], 2), "baseline_upper": round(hi[i], 2),
            "scenario_lower": round(lo[i] + cum[i], 2), "scenario_upper": round(hi[i] + cum[i], 2),
            "baseline_usd": round(base[i] * usd_rate, 2), "scenario_usd": round(scen_bal[i] * usd_rate * translate, 2),
            "baseline_level": rules.classify(base[i], threshold), "scenario_level": rules.classify(scen_bal[i], threshold),
            "delta": round(float(delta[i]), 2),
        })

    def kpis(bal):
        below = bal < threshold
        first = next((series[i]["date"] for i, b in enumerate(below) if b), None)
        shortfall = np.clip(threshold - bal, 0, None)
        return {
            "min_balance": float(bal.min()), "min_gap": float(bal.min() - threshold),
            "days_below_threshold": int(below.sum()), "first_breach_date": first,
            "worst_level": rules.worst(rules.classify(b, threshold) for b in bal),
            "funding_cost": float(shortfall.sum() * OVERDRAFT_RATE / 360),
            "deployable_surplus": rules.deployable_surplus(bal.min(), threshold),
            "end_balance": float(bal[-1]),
        }

    opening = float(prep.positions[int(entity_id)].get(prep.as_of, base[0]))
    result = {
        "entity": {"id": int(entity_id), "code": ent.code, "name": ent["name"], "currency": currency,
                   "region": ent.region, "threshold": threshold},
        "as_of": str(prep.as_of.date()), "horizon": horizon, "forecast_run_id": run_id,
        "parameters": p, "scenario_type": scenario_type(p), "usd_rate": usd_rate,
        "series": series,
        "baseline": kpis(base), "scenario": kpis(scen_bal),
        "impact": {
            "change_at_end": float(cum[-1]),
            "min_gap_change": float((scen_bal.min() - base.min())),
            "fx_translation_usd": float(opening * usd_rate * fx) if currency != "USD" else 0.0,
            "fx_transaction_impact": fx_transaction,
            "interest_delta": interest_delta,
            "idle_interest_opportunity": rules.deployable_surplus(scen_bal.min(), threshold) * INVEST_RATE * horizon / 360,
            "affected_transactions": int(affected.sum()),
        },
        "notes": notes or ["No shock applied: scenario equals the baseline forecast."],
    }

    if persist:
        result["scenario_id"] = _persist(int(entity_id), currency, result)
    return result


def _persist(entity_id, currency, result):
    with transaction.atomic():
        sc = Scenario.objects.create(
            entity_id=entity_id, scenario_type=result["scenario_type"],
            parameters={**result["parameters"], "horizon": result["horizon"],
                        "forecast_run_id": result["forecast_run_id"], "as_of": result["as_of"]},
        )
        ScenarioResult.objects.bulk_create([
            ScenarioResult(
                scenario=sc, forecast_date=s["date"], currency=currency,
                projected_balance=Decimal(str(s["scenario"])), baseline_balance=Decimal(str(s["baseline"])),
                liquidity_gap=Decimal(str(round(s["scenario"] - result["entity"]["threshold"], 2))),
            )
            for s in result["series"]
        ])
    return sc.id
