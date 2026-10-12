"""Counterparty risk summary for the Counterparty Risk page (uses Script 1's R(t))."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import rules
from .script1_prepare import prepare


def counterparty_summary(entity_ids=None, as_of=None):
    prep = prepare(as_of)
    tx = prep.tx
    hist = tx[tx.transaction_date <= prep.as_of]
    if entity_ids is not None:
        hist = hist[hist.entity_id.isin(entity_ids)]
        tx = tx[tx.entity_id.isin(entity_ids)]
    if hist.empty:
        return {"as_of": str(prep.as_of.date()), "model": prep.risk.as_dict(), "counterparties": []}

    hist = hist.assign(delay=hist.lag_days.clip(lower=0), month=hist.transaction_date.dt.to_period("M"))
    months = pd.period_range(end=prep.as_of.to_period("M"), periods=6, freq="M")
    names = prep.entities["code"].to_dict()

    rows = []
    for cp, g in hist.groupby("counterparty"):
        score = float(g.R.mean())
        trend = g.groupby("month").delay.mean().reindex(months).fillna(0).round(2).tolist()
        by_entity = (g.groupby("entity_id").agg(n=("R", "size"), p_fail=("p_fail", "mean"), R=("R", "mean"))
                     .reset_index())
        pending = tx[(tx.counterparty == cp) & (tx.transaction_date > prep.as_of)]
        rows.append({
            "name": cp,
            "rating": rules.grade(score),
            "risk_score": round(score, 4),                         # mean R(t), 0–1
            "p_fail": round(float(g.p_fail.mean()), 4),            # expected failure probability
            "p_late": round(float(g.p_late.mean()), 4),
            "transactions": int(len(g)),
            "failure_rate": round(float(g.failed.mean()) * 100, 2),   # observed, %
            "late_share": round(float((g.lag_days > 0).mean()) * 100, 2),
            "avg_delay": round(float(g.delay.mean()), 2),          # avg days late (early = 0)
            "avg_timing": round(float(g.lag_days.mean()), 2),      # avg actual − due (negative = early)
            "trend": trend,
            "trend_months": [str(m) for m in months],
            "pending_inflow": round(float(pending[pending.direction == "inflow"].amount.sum()), 2),
            "entities": [
                {"entity_id": int(r.entity_id), "entity": names.get(r.entity_id, str(r.entity_id)),
                 "transactions": int(r.n), "p_fail": round(float(r.p_fail), 4), "risk_score": round(float(r.R), 4)}
                for r in by_entity.itertuples()
            ],
        })
    rows.sort(key=lambda r: -r["risk_score"])
    return {
        "as_of": str(prep.as_of.date()),
        "model": prep.risk.as_dict(),
        "rating_bands": {"A": "< 0.01", "B": "0.01 – 0.05", "C": "0.05 – 0.18", "D": "≥ 0.18"},
        "counterparties": rows,
    }
