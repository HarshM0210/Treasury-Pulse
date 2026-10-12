"""
Counterparty risk R(t) for every transaction, on a 0-1 scale.

Algorithm (agreed design):

  p0      = global failure rate
  p̂_e     = (F_e + k_e·p0) / (N_e + k_e)                 entity rate, shrunk to global
  p̂_AB    = (F_AB + k_p·p̂_A) / (N_AB + k_p)              entity–counterparty pair rate,
                                                          shrunk to its own entity
  E[p | A] = Σ_B (N_AB / N_A) · p̂_AB                     expected failure prob. of entity A
  p_fail(t) = p̂_AB  for the pair of transaction t
  p_late(t) = P(actual date > due date | frequency of t)
  R(t)      = 1 − (1 − p_fail(t)) · (1 − p_late(t))

k_e and k_p are estimated from the data by the method of moments
(empirical Bayes): k = p(1−p) / var_between − 1, where var_between is the
spread of observed rates minus the spread expected from sampling noise.
Only history up to as_of is used, so there is no look-ahead.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

K_MAX = 1e6          # "no real differences": everything shrinks to the parent rate
MIN_PAIR_ROWS = 50   # pairs used to estimate k_p


@dataclass
class RiskModel:
    p0: float
    k_entity: float
    k_pair: float
    entity_p_fail: dict = field(default_factory=dict)       # entity_id -> p̂_e
    entity_expected: dict = field(default_factory=dict)     # entity_id -> E[p | A]
    pair_p_fail: dict = field(default_factory=dict)         # (entity_id, counterparty) -> p̂_AB
    p_late: dict = field(default_factory=dict)              # frequency -> P(late)
    p_late_default: float = 0.0

    def as_dict(self):
        return {
            "global_failure_rate": self.p0,
            "k_entity": self.k_entity,
            "k_pair": self.k_pair,
            "p_late_by_frequency": self.p_late,
        }


def _k_by_moments(rates, sizes, parent):
    """k = mean(parent(1-parent)) / var_between - 1 ; huge if no real spread."""
    rates, sizes, parent = map(np.asarray, (rates, sizes, parent))
    if len(rates) < 2:
        return K_MAX
    noise = np.mean(parent * (1 - parent) / sizes)
    var_between = np.mean((rates - parent) ** 2) - noise
    if var_between <= 0:
        return K_MAX
    return float(min(K_MAX, max(0.0, np.mean(parent * (1 - parent)) / var_between - 1)))


def fit_risk(history: pd.DataFrame) -> RiskModel:
    """history: rows with known outcome (transaction_date <= as_of)."""
    if history.empty:
        return RiskModel(p0=0.0, k_entity=K_MAX, k_pair=K_MAX)

    failed = history["failed"].astype(float)
    p0 = float(failed.mean())

    # Entity level, shrunk to the global rate
    ent = history.assign(f=failed).groupby("entity_id")["f"].agg(F="sum", N="size")
    k_e = _k_by_moments(ent.F / ent.N, ent.N, np.full(len(ent), p0))
    p_e = (ent.F + k_e * p0) / (ent.N + k_e)

    # Pair level, shrunk to its own entity's rate
    pair = (history.assign(f=failed)
            .groupby(["entity_id", "counterparty"])["f"].agg(F="sum", N="size").reset_index())
    pair["parent"] = pair["entity_id"].map(p_e)
    big = pair[pair.N >= MIN_PAIR_ROWS]
    k_p = _k_by_moments(big.F / big.N, big.N, big.parent) if len(big) else K_MAX
    pair["p_fail"] = (pair.F + k_p * pair.parent) / (pair.N + k_p)

    # Expected failure probability per entity, weighted by transaction share
    pair["w"] = pair.N / pair.groupby("entity_id").N.transform("sum")
    expected = (pair.w * pair.p_fail).groupby(pair.entity_id).sum()

    # Lateness by payment frequency
    late = history["lag_days"] > 0
    p_late = late.groupby(history["frequency"]).mean()

    return RiskModel(
        p0=p0,
        k_entity=float(k_e),
        k_pair=float(k_p),
        entity_p_fail={int(k): float(v) for k, v in p_e.items()},
        entity_expected={int(k): float(v) for k, v in expected.items()},
        pair_p_fail={(int(e), c): float(p) for e, c, p in pair[["entity_id", "counterparty", "p_fail"]].itertuples(index=False)},
        p_late={str(k): float(v) for k, v in p_late.items()},
        p_late_default=float(late.mean()),
    )


def apply_risk(tx: pd.DataFrame, model: RiskModel) -> pd.DataFrame:
    """Add p_fail, p_late and R columns to every transaction row."""
    keys = list(zip(tx["entity_id"].astype(int), tx["counterparty"]))
    p_fail = pd.Series([model.pair_p_fail.get(k, np.nan) for k in keys], index=tx.index)
    entity_fallback = tx["entity_id"].map(model.entity_p_fail)
    tx["p_fail"] = p_fail.fillna(entity_fallback).fillna(model.p0)
    tx["p_late"] = tx["frequency"].map(model.p_late).fillna(model.p_late_default)
    tx["R"] = 1 - (1 - tx["p_fail"]) * (1 - tx["p_late"])
    return tx
