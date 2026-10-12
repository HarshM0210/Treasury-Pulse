"""Live tools: answer each intent from the Treasury Pulse database and ML outputs.

Every tool is scoped to the request user's entities (get_allowed_entities), so an
Analyst only ever sees London/Paris, a Manager only their regions, etc.

Forecast / summary / what-if / counterparties / upcoming reuse the existing API
views in-process (same scoping, same numbers as the dashboard pages). Historical
analytics (settlements, trends, flows, regions) are ORM aggregations.

Each tool returns:
    {"facts": str,            # deterministic answer text (always correct, no LLM)
     "data": dict,            # compact evidence (sent to the UI and the LLM)
     "visualization": dict|None,
     "needs_input": str|None} # ask the user for a missing parameter
"""
from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from rest_framework.test import APIRequestFactory, force_authenticate

from ml import rules
from treasury import analytics_views as av
from treasury.models import Alert, Entity, Transaction
from treasury.scoping import get_allowed_entities

from .intent import CITY_ALIASES

_factory = APIRequestFactory(SERVER_NAME="localhost")
SEVERITY_RANK = {"EMERGENCY": 0, "CRITICAL": 1, "WARNING": 2, "OK": 3, "SURPLUS": 4}
CITY_NAMES = {"NY": "New York", "HK": "Hong Kong", "SAO_PAULO": "Sao Paulo"}


class ToolError(RuntimeError):
    pass


# ─── helpers ───────────────────────────────────────────────────────────

def _call(view, user, method="get", path="/", data=None, **kwargs):
    req = _factory.post(path, data, format="json") if method == "post" else _factory.get(path, data or {})
    force_authenticate(req, user=user)
    resp = view(req, **kwargs)
    if resp.status_code >= 400:
        detail = resp.data.get("detail") if isinstance(resp.data, dict) else None
        raise ToolError(str(detail or f"Request failed ({resp.status_code})."))
    return resp.data


def money(v, ccy=""):
    if v is None:
        return "n/a"
    sign = "−" if v < 0 else ""
    v = abs(float(v))
    if v >= 1e9:
        s = f"{v / 1e9:,.2f}B"
    elif v >= 1e6:
        s = f"{v / 1e6:,.2f}M"
    elif v >= 1e4:
        s = f"{v / 1e3:,.1f}K"
    else:
        s = f"{v:,.0f}"
    return f"{sign}{s} {ccy}".strip()


def _code(name):
    return av._code(name)


def entity_directory():
    """All entities (for name resolution); access is checked separately."""
    out = []
    for e in Entity.objects.all().order_by("id"):
        code = _code(e.name).upper()
        cur = (Transaction.objects.filter(entity=e).values_list("currency", flat=True).first()) or ""
        out.append({"id": e.id, "code": code, "name": e.name, "region": e.region, "country": e.country,
                    "city": CITY_NAMES.get(code, code.replace("_", " ").title()), "currency": cur})
    return out


def counterparty_names():
    return list(Transaction.objects.exclude(counterparty="").values_list("counterparty", flat=True)
                .distinct().order_by("counterparty"))


def _allowed_ids(user):
    return set(get_allowed_entities(user).values_list("id", flat=True))


def _entity_for(user, det, required=True, purpose="this"):
    """(entity_id, needs_input) — checks access."""
    eid = det.get("entity_id")
    allowed = _allowed_ids(user)
    if eid is None:
        if len(allowed) == 1:
            return next(iter(allowed)), None
        if not required:
            return None, None
        names = ", ".join(sorted(_code(n) for n in Entity.objects.filter(id__in=allowed).values_list("name", flat=True)))
        return None, f"Which entity should I use for {purpose}? You can access: {names}."
    if eid not in allowed:
        label = (det.get("entity") or {}).get("code") or f"entity {eid}"
        raise ToolError(f"You do not have access to {label}. Ask an Admin to extend your entity scope.")
    return eid, None


def _summary(user):
    return _call(av.analytics_summary, user)


def _first_breach(points, key, threshold):
    return next((p["date"] for p in points if p[key] is not None and p[key] < threshold), None)


def _tx_scope(user, det):
    qs = Transaction.objects.filter(entity__in=get_allowed_entities(user))
    if det.get("entity_id"):
        _entity_for(user, det)
        qs = qs.filter(entity_id=det["entity_id"])
    if det.get("currency"):
        qs = qs.filter(currency=det["currency"])
    if det.get("counterparty"):
        qs = qs.filter(counterparty=det["counterparty"])
    return qs


def _scope_label(det):
    parts = []
    if det.get("entity"):
        parts.append(det["entity"].get("code", ""))
    if det.get("currency"):
        parts.append(det["currency"])
    if det.get("counterparty"):
        parts.append(det["counterparty"])
    return f" ({', '.join(p for p in parts if p)})" if parts else ""


# ─── tools ─────────────────────────────────────────────────────────────

HELP = ("I answer from live Treasury Pulse data for the entities you can access. Try:\n"
        "• \"Which entities face a shortfall?\"\n"
        "• \"Show the 14-day forecast for London\"\n"
        "• \"What if we delay payments by 3 days in New York?\"\n"
        "• \"What if EUR weakens 10% for Paris?\" / \"rates +100 bps for Tokyo\"\n"
        "• \"Downgrade vendor_Y to D for Dubai\"\n"
        "• \"Which counterparties are rated D?\" / \"Tell me about client_A\"\n"
        "• \"Where is idle cash we could deploy?\"\n"
        "• \"Settlement failure rate in Mumbai\" / \"Monthly trend for Singapore\"\n"
        "• \"Upcoming payments this week\"")


def tool_help(user, det):
    return {"facts": HELP, "data": {}, "visualization": None}


def tool_summary(user, det):
    s = _summary(user)
    ents = s.get("entities", [])
    if not ents:
        return {"facts": "No entities are in your scope yet.", "data": {}, "visualization": None}
    if det.get("entity_id"):
        _entity_for(user, det)
        e = next((x for x in ents if x["id"] == det["entity_id"]), None)
        if e:
            breach = f"; first projected below threshold on {e['first_breach_date']}" if e.get("first_breach_date") else ""
            facts = (f"{e['code']} ({e['currency']}), as of {s['as_of']}: balance {money(e['balance'], e['currency'])}, "
                     f"threshold {money(e['threshold'], e['currency'])}. Lowest projected balance in the next "
                     f"{s['horizon']} days is {money(e['projected_min'], e['currency'])} on {e['projected_min_date']} "
                     f"(level {e['level']}{breach}). Expected inflows {money(e['inflow_30d'], e['currency'])}, "
                     f"outflows {money(e['outflow_30d'], e['currency'])}.")
            return {"facts": facts, "data": {"as_of": s["as_of"], "entity": e}, "visualization": None}
    by = defaultdict(list)
    for e in ents:
        by[e["level"]].append(e)
    counts = ", ".join(f"{len(by[l])} {l.lower()}" for l in rules.LEVELS if by.get(l))
    lines = [f"Liquidity position as of {s['as_of']} across your {len(ents)} entities ({counts}); "
             f"{s.get('open_alerts', 0)} open alert(s)."]
    risky = sorted([e for e in ents if e["level"] in ("EMERGENCY", "CRITICAL", "WARNING")],
                   key=lambda e: (SEVERITY_RANK[e["level"]], e.get("first_breach_date") or "9999"))
    for e in risky[:5]:
        when = f"below threshold from {e['first_breach_date']}" if e.get("first_breach_date") else "headroom under 10%"
        lines.append(f"• {e['level']}: {e['code']} ({e['currency']}) — {when}; lowest "
                     f"{money(e['projected_min'], e['currency'])} on {e['projected_min_date']}.")
    if not risky:
        lines.append("• No entity is projected to breach its threshold in the forecast window.")
    surplus = [e for e in ents if e.get("deployable_surplus", 0) > 0]
    if surplus:
        top = max(surplus, key=lambda e: e["deployable_surplus"] * e.get("usd_rate", 1))
        lines.append(f"• Largest deployable surplus: {top['code']} {money(top['deployable_surplus'], top['currency'])} "
                     f"(above threshold + 20% buffer).")
    viz = {"type": "bar", "title": "Lowest projected headroom vs threshold (USD equivalent)", "xKey": "entity",
           "series": [{"key": "headroom_usd", "label": "Headroom (USD eq.)"}], "signed": True,
           "data": [{"entity": e["code"], "headroom_usd": round(e["gap"] * e.get("usd_rate", 1.0))}
                    for e in sorted(ents, key=lambda e: e["gap"] * e.get("usd_rate", 1.0))]}
    data = {"as_of": s["as_of"], "open_alerts": s.get("open_alerts"),
            "entities": [{k: e.get(k) for k in ("code", "currency", "level", "balance", "threshold", "projected_min",
                                                 "projected_min_date", "first_breach_date", "deployable_surplus")}
                         for e in ents]}
    return {"facts": "\n".join(lines), "data": data, "visualization": viz}


def tool_forecast(user, det):
    horizon = det.get("horizon") or 30
    eid, _ = _entity_for(user, det, required=False)
    if eid is None:
        t = _call(av.analytics_forecast_total, user, path="/", data={"horizon": horizon})
        pts = t.get("forecast", [])
        if not pts:
            return {"facts": "No forecast is available yet.", "data": {}, "visualization": None}
        low = min(pts, key=lambda p: p["forecast"])
        s = _summary(user)
        risky = [e["code"] for e in s.get("entities", []) if e["level"] in ("EMERGENCY", "CRITICAL")]
        facts = (f"Portfolio {len(pts)}-day forecast as of {t['as_of']} (USD equivalent across your entities): "
                 f"ends at {money(pts[-1]['forecast'], 'USD')}, lowest {money(low['forecast'], 'USD')} on {low['date']} "
                 f"vs a combined threshold of {money(t['threshold'], 'USD')}.")
        if risky:
            facts += f" Entities projected below or near threshold: {', '.join(risky)} — ask for one by name for detail."
        viz = {"type": "line", "title": f"Portfolio forecast · {len(pts)} days (USD eq.)", "xKey": "date",
               "series": [{"key": "forecast", "label": "Forecast"}, {"key": "lower", "label": "80% low"},
                          {"key": "upper", "label": "80% high"}],
               "threshold": t["threshold"], "data": pts}
        return {"facts": facts, "data": {"as_of": t["as_of"], "currency": "USD", "lowest": low,
                                         "end": pts[-1], "threshold": t["threshold"]}, "visualization": viz}
    f = _call(av.analytics_forecast, user, path="/", data={"horizon": horizon, "history": 1}, entity_id=eid)
    e, pts, ccy = f["entity"], f["forecast"], f["entity"]["currency"]
    thr = e["threshold"]
    breach = _first_breach(pts, "forecast", thr)
    risk_breach = _first_breach(pts, "lower", thr)
    facts = (f"{e['code']} ({ccy}) {f['horizon']}-day forecast as of {f['as_of']}: balance today "
             f"{money(f['balance'], ccy)}, projected {money(f['projected'], ccy)} on {pts[-1]['date']}. "
             f"Lowest point {money(f['projected_min'], ccy)} on {f['projected_min_date']} vs threshold {money(thr, ccy)}. ")
    if breach:
        facts += f"Projected to fall below threshold on {breach} (worst level {f['worst_level']})."
    elif risk_breach:
        facts += (f"The central forecast stays above threshold, but the 80% band dips below it from {risk_breach} "
                  f"(lowest lower bound {money(f['lowest_lower_bound'], ccy)}).")
    else:
        facts += f"Stays above threshold for the whole window, including the 80% band (worst level {f['worst_level']})."
    viz = {"type": "line", "title": f"{e['code']} forecast · {f['horizon']} days ({ccy})", "xKey": "date",
           "series": [{"key": "forecast", "label": "Forecast"}, {"key": "lower", "label": "80% low"},
                      {"key": "upper", "label": "80% high"}],
           "threshold": thr, "data": [{k: p[k] for k in ("date", "forecast", "lower", "upper")} for p in pts]}
    data = {k: f[k] for k in ("as_of", "horizon", "balance", "projected", "projected_min", "projected_min_date",
                              "lowest_lower_bound", "worst_level")}
    data.update(entity=e, first_breach_date=breach)
    return {"facts": facts, "data": data, "visualization": viz}


def tool_alerts(user, det):
    qs = (Alert.objects.filter(entity__in=get_allowed_entities(user)).exclude(status="RESOLVED")
          .select_related("entity"))
    if det.get("entity_id"):
        _entity_for(user, det)
        qs = qs.filter(entity_id=det["entity_id"])
    alerts = sorted(qs, key=lambda a: (SEVERITY_RANK.get(a.severity, 9), str(a.metric_date or "")))
    if not alerts:
        base = tool_summary(user, det)
        return {"facts": "There are no open or acknowledged liquidity alerts" + _scope_label(det) + ".\n" + base["facts"],
                "data": base["data"], "visualization": base["visualization"]}
    lines = [f"{len(alerts)} active liquidity alert(s){_scope_label(det)}:"]
    rows = []
    for a in alerts[:6]:
        prob = f"; breach probability {a.breach_probability:.0%}" if a.breach_probability is not None else ""
        lines.append(f"• {a.severity} — {_code(a.entity.name)} ({a.currency}): {a.title or 'liquidity gap'}"
                     f"{prob}; status {a.status}.")
        rows.append({"entity": _code(a.entity.name), "severity": a.severity, "status": a.status, "currency": a.currency,
                     "title": a.title, "metric_date": str(a.metric_date), "breach_probability": a.breach_probability,
                     "liquidity_gap": float(a.liquidity_gap)})
    lines.append("Open Risk & Alerts to acknowledge them, or ask me for a what-if (e.g. delay payments by 3 days).")
    return {"facts": "\n".join(lines), "data": {"alerts": rows}, "visualization": None}


def tool_surplus(user, det):
    s = _summary(user)
    ents = [e for e in s.get("entities", []) if e.get("deployable_surplus", 0) > 0]
    if det.get("entity_id"):
        ents = [e for e in ents if e["id"] == det["entity_id"]]
    if not ents:
        return {"facts": "No entity has cash above its threshold + 20% buffer for the whole forecast window.",
                "data": {}, "visualization": None}
    ents.sort(key=lambda e: -e["deployable_surplus"] * e.get("usd_rate", 1))
    total_usd = sum(e["deployable_surplus"] * e.get("usd_rate", 1) for e in ents)
    lines = [f"Deployable surplus as of {s['as_of']} (cash that stays above threshold + 20% for the next "
             f"{s['horizon']} days):"]
    for e in ents[:8]:
        lines.append(f"• {e['code']}: {money(e['deployable_surplus'], e['currency'])} "
                     f"(≈ {money(e['deployable_surplus'] * e.get('usd_rate', 1), 'USD')})")
    lines.append(f"Total ≈ {money(total_usd, 'USD')} equivalent. At 4% p.a. that is ≈ "
                 f"{money(total_usd * 0.04 * s['horizon'] / 360, 'USD')} over {s['horizon']} days.")
    viz = {"type": "bar", "title": "Deployable surplus (USD equivalent)", "xKey": "entity",
           "series": [{"key": "surplus_usd", "label": "Surplus (USD eq.)"}],
           "data": [{"entity": e["code"], "surplus_usd": round(e["deployable_surplus"] * e.get("usd_rate", 1))} for e in ents]}
    return {"facts": "\n".join(lines), "data": {"as_of": s["as_of"], "total_usd": total_usd,
                                                "entities": [{k: e[k] for k in ("code", "currency", "deployable_surplus")}
                                                             for e in ents]},
            "visualization": viz}


def tool_counterparties(user, det):
    c = _call(av.analytics_counterparties, user)
    cps = c.get("counterparties", [])
    if not cps:
        return {"facts": "No counterparty data is available for your entities.", "data": {}, "visualization": None}
    name = det.get("counterparty")
    if name:
        cp = next((x for x in cps if x["name"] == name), None)
        if not cp:
            return {"facts": f"{name} has no transactions with your entities.", "data": {}, "visualization": None}
        ents = sorted(cp.get("entities", []), key=lambda x: -x["risk_score"])[:3]
        facts = (f"{cp['name']}: rating {cp['rating']}, risk score R = {cp['risk_score']:.3f} "
                 f"(p_fail {cp['p_fail']:.1%}, p_late {cp['p_late']:.1%}). {cp['transactions']:,} transactions, "
                 f"{cp['failure_rate']}% failed, {cp['late_share']}% paid late. Pending inflows "
                 f"{money(cp.get('pending_inflow'), 'USD')} (USD eq.).")
        if ents:
            facts += " Riskiest relationships: " + ", ".join(f"{x['entity']} R={x['risk_score']:.3f}" for x in ents) + "."
        viz = {"type": "bar", "title": f"{cp['name']} monthly failure rate (%)", "xKey": "month",
               "series": [{"key": "failure_rate", "label": "Failure rate %"}],
               "data": [{"month": m, "failure_rate": v} for m, v in zip(cp.get("trend_months", []), cp.get("trend", []))]}
        return {"facts": facts, "data": {"counterparty": {k: v for k, v in cp.items() if k != "entities"}},
                "visualization": viz if viz["data"] else None}
    rated = [x for x in cps if not det.get("rating") or x["rating"] == det["rating"]]
    dist = defaultdict(int)
    for x in cps:
        dist[x["rating"]] += 1
    lines = [f"{len(cps)} counterparties for your entities, as of {c.get('as_of')}: "
             + ", ".join(f"{dist[g]} rated {g}" for g in "ABCD" if dist.get(g)) + "."]
    if det.get("rating") and not rated:
        lines.append(f"None is currently rated {det['rating']}.")
    top = sorted(rated, key=lambda x: -x["risk_score"])[:5]
    for x in top:
        lines.append(f"• {x['name']}: {x['rating']} (R {x['risk_score']:.3f}; {x['failure_rate']}% failed, "
                     f"{x['late_share']}% late; {x['transactions']:,} tx)")
    lines.append("R = 1 − (1 − p_fail)(1 − p_late); bands A < 0.01, B < 0.05, C < 0.18, D ≥ 0.18.")
    viz = {"type": "bar", "title": "Counterparty risk score R", "xKey": "name",
           "series": [{"key": "risk_score", "label": "Risk score R"}],
           "data": [{"name": x["name"], "risk_score": x["risk_score"]}
                    for x in sorted(rated, key=lambda x: -x["risk_score"])[:12]]}
    return {"facts": "\n".join(lines), "data": {"distribution": dict(dist), "top": top},
            "visualization": viz if viz["data"] else None}


def tool_upcoming(user, det):
    days = det.get("horizon") or 7
    u = _call(av.analytics_upcoming, user, path="/", data={"days": days, "limit": 50})
    ev = u.get("events", [])
    if det.get("entity_id"):
        _entity_for(user, det)
        ev = [x for x in ev if x["entity_id"] == det["entity_id"]]
    if det.get("direction"):
        ev = [x for x in ev if x["direction"] == det["direction"]]
    if not ev:
        return {"facts": f"No scheduled payments in the next {days} days{_scope_label(det)}.", "data": {}, "visualization": None}
    lines = [f"Largest scheduled flows in the next {days} days after {u['as_of']}{_scope_label(det)}:"]
    for x in ev[:8]:
        arrow = "in" if x["direction"] == "inflow" else "out"
        lines.append(f"• {x['date']} {x['entity']}: {arrow} {money(x['amount'], x['currency'])} — {x['description']}")
    return {"facts": "\n".join(lines), "data": {"as_of": u["as_of"], "events": ev[:8]}, "visualization": None}


def tool_transactions(user, det):
    qs = _tx_scope(user, det)
    if det.get("direction"):
        qs = qs.filter(direction=det["direction"])
    n = qs.count()
    if not n:
        return {"facts": f"No transactions match{_scope_label(det)}.", "data": {}, "visualization": None}
    agg = qs.aggregate(failed=Count("id", filter=Q(settlement_status="failed")))
    latest = list(qs.select_related("entity").order_by("-transaction_date", "-id")[:5])
    lines = [f"{n:,} transactions{_scope_label(det)}; {agg['failed']:,} failed ({agg['failed'] / n:.1%})."
             " Most recent:"]
    for t in latest:
        lines.append(f"• {t.transaction_date} {_code(t.entity.name)} {t.direction} {money(float(t.amount), t.currency)} "
                     f"— {t.counterparty}, {t.product_type.replace('_', ' ')}, {t.settlement_status}")
    lines.append("The Transactions page has the full list with filters.")
    return {"facts": "\n".join(lines), "data": {"count": n, "failed": agg["failed"]}, "visualization": None}


def tool_what_if(user, det):
    p = dict(det.get("what_if_params") or {})
    eid, ask = _entity_for(user, det, purpose="the scenario")
    if ask:
        return {"facts": "", "data": {}, "visualization": None, "needs_input": ask}
    if not p:
        return {"facts": "", "data": {}, "visualization": None, "needs_input": (
            "Which assumption should I test? For example: delay payments by 3 days, postpone capex 20 days, "
            "EUR weakens 10%, rates +100 bps, or downgrade vendor_Y to D.")}
    if p.get("payment_delay_days", 0) > 5:
        return {"facts": "", "data": {}, "visualization": None,
                "needs_input": "The payment-delay lever supports 0–5 days. How many days (1–5)?"}
    horizon = det.get("horizon") or 30
    r = _call(av.analytics_what_if, user, method="post", path="/",
              data={"entity_id": eid, "horizon": horizon, "parameters": p})
    e, ccy, b, s, imp = r["entity"], r["entity"]["currency"], r["baseline"], r["scenario"], r["impact"]
    lines = [f"What-if for {e['code']} ({ccy}), {r['horizon']} days from {r['as_of']} — " + "; ".join(r["notes"]) + "."]
    lines.append(f"• Lowest balance: {money(s['min_balance'], ccy)} vs baseline {money(b['min_balance'], ccy)} "
                 f"(threshold {money(e['threshold'], ccy)}).")
    lines.append(f"• Days below threshold: {s['days_below_threshold']} vs baseline {b['days_below_threshold']}"
                 + (f"; first breach {s['first_breach_date']}" if s.get("first_breach_date") else "") + ".")
    lines.append(f"• Change in balance at day {r['horizon']}: {money(imp['change_at_end'], ccy)}; "
                 f"overdraft cost {money(s['funding_cost'], ccy)} vs {money(b['funding_cost'], ccy)}.")
    if p.get("fx_shock_pct"):
        lines.append(f"• FX: translation effect {money(imp['fx_translation_usd'], 'USD')}; cross-border payments "
                     f"revalued by {money(imp['fx_transaction_impact'], ccy)}.")
    if p.get("rate_shock_bps"):
        lines.append(f"• Interest income/expense change: {money(imp['interest_delta'], ccy)}.")
    lines.append(f"Modelled change on {imp['affected_transactions']} pending transactions; the forecast model is not "
                 f"refitted. Saved as scenario #{r.get('scenario_id')}.")
    viz = {"type": "line", "title": f"{e['code']} baseline vs scenario ({ccy})", "xKey": "date",
           "series": [{"key": "baseline", "label": "Baseline"}, {"key": "scenario", "label": "Scenario"}],
           "threshold": e["threshold"],
           "data": [{"date": x["date"], "baseline": x["baseline"], "scenario": x["scenario"]} for x in r["series"]]}
    data = {"entity": e, "as_of": r["as_of"], "parameters": r["parameters"], "scenario_type": r["scenario_type"],
            "baseline": b, "scenario": s, "impact": imp, "scenario_id": r.get("scenario_id")}
    return {"facts": "\n".join(lines), "data": data, "visualization": viz}


# ─── historical analytics (ORM) ────────────────────────────────────────

def tool_settlements(user, det):
    qs = _tx_scope(user, det)
    n = qs.count()
    if not n:
        return {"facts": f"No transactions match{_scope_label(det)}.", "data": {}, "visualization": None}
    failed = qs.filter(settlement_status="failed").count()
    by_cp = (qs.values("counterparty").annotate(n=Count("id"), f=Count("id", filter=Q(settlement_status="failed")))
             .filter(n__gte=30))
    worst = sorted(by_cp, key=lambda r: -r["f"] / r["n"])[:5]
    lines = [f"Historical settlements{_scope_label(det)}: {n:,} transactions, {failed:,} failed "
             f"({failed / n:.2%})."]
    if worst and not det.get("counterparty"):
        lines.append("Highest failure rates: " + ", ".join(f"{r['counterparty']} {r['f'] / r['n']:.1%}" for r in worst) + ".")
    viz = {"type": "bar", "title": "Failure rate by counterparty (%)", "xKey": "counterparty",
           "series": [{"key": "failure_rate", "label": "Failure rate %"}],
           "data": [{"counterparty": r["counterparty"], "failure_rate": round(100 * r["f"] / r["n"], 2)}
                    for r in sorted(by_cp, key=lambda r: -r["f"] / r["n"])[:12]]}
    return {"facts": "\n".join(lines), "data": {"total": n, "failed": failed, "failure_rate": failed / n},
            "visualization": viz if len(viz["data"]) > 1 else None}


def tool_settlement_causes(user, det):
    qs = _tx_scope(user, det)
    n = qs.count()
    if not n:
        return {"facts": f"No transactions match{_scope_label(det)}.", "data": {}, "visualization": None}

    def rates(field):
        rows = qs.values(field).annotate(n=Count("id"), f=Count("id", filter=Q(settlement_status="failed"))).filter(n__gte=50)
        return sorted(({"key": str(r[field]), "rate": r["f"] / r["n"], "n": r["n"]} for r in rows), key=lambda r: -r["rate"])

    prod, freq, xb = rates("product_type"), rates("frequency"), rates("is_cross_border")
    lines = ["The dataset records whether a payment failed, but not why (there is no failure-reason field), "
             "so I can only show where failures concentrate" + _scope_label(det) + ":"]
    if prod:
        lines.append("• By product: " + ", ".join(f"{r['key'].replace('_', ' ')} {r['rate']:.1%}" for r in prod[:4]) + ".")
    if freq:
        lines.append("• By frequency: " + ", ".join(f"{r['key']} {r['rate']:.1%}" for r in freq) + ".")
    if len(xb) == 2:
        d = {r["key"]: r["rate"] for r in xb}
        lines.append(f"• Cross-border {d.get('True', 0):.1%} vs domestic {d.get('False', 0):.1%}.")
    lines.append("Late payment, not failure, is driven by frequency: ad-hoc, daily and weekly flows are late far "
                 "more often than monthly or quarterly ones (see Counterparty Risk).")
    viz = {"type": "bar", "title": "Failure rate by product type (%)", "xKey": "product",
           "series": [{"key": "failure_rate", "label": "Failure rate %"}],
           "data": [{"product": r["key"].replace("_", " "), "failure_rate": round(100 * r["rate"], 2)} for r in prod[:10]]}
    return {"facts": "\n".join(lines), "data": {"by_product": prod[:10], "by_frequency": freq, "cross_border": xb},
            "visualization": viz if viz["data"] else None}


def tool_monthly_trend(user, det):
    qs = _tx_scope(user, det)
    if det.get("direction"):
        qs = qs.filter(direction=det["direction"])
    rows = list(qs.annotate(m=TruncMonth("transaction_date")).values("m", "currency")
                .annotate(n=Count("id"),
                          inflow=Sum("amount", filter=Q(direction="inflow", settlement_status="settled")),
                          outflow=Sum("amount", filter=Q(direction="outflow", settlement_status="settled")))
                .order_by("m"))
    if not rows:
        return {"facts": f"No transactions match{_scope_label(det)}.", "data": {}, "visualization": None}
    currencies = sorted({r["currency"] for r in rows})
    months = defaultdict(int)
    for r in rows:
        months[r["m"].strftime("%Y-%m")] += r["n"]
    peak = max(months.items(), key=lambda kv: kv[1])
    facts = (f"{sum(months.values()):,} transactions{_scope_label(det)} across {len(months)} months; "
             f"busiest month {peak[0]} ({peak[1]:,}).")
    if len(currencies) == 1:
        ccy = currencies[0]
        data = [{"month": r["m"].strftime("%Y-%m"),
                 "net": round(float(r["inflow"] or 0) - float(r["outflow"] or 0))} for r in rows]
        best = max(data, key=lambda d: d["net"])
        worst = min(data, key=lambda d: d["net"])
        facts += (f" Settled net flow in {ccy}: best {best['month']} {money(best['net'], ccy)}, "
                  f"worst {worst['month']} {money(worst['net'], ccy)}.")
        viz = {"type": "bar", "title": f"Settled net cash flow per month ({ccy})", "xKey": "month",
               "series": [{"key": "net", "label": f"Net flow ({ccy})"}], "signed": True, "data": data}
    else:
        viz = {"type": "bar", "title": "Transactions per month", "xKey": "month",
               "series": [{"key": "transactions", "label": "Transactions"}],
               "data": [{"month": m, "transactions": n} for m, n in sorted(months.items())]}
        facts += " Amounts span several currencies; name an entity or currency for a net-flow trend."
    return {"facts": facts, "data": {"months": dict(months), "currencies": currencies}, "visualization": viz}


def tool_regional(user, det):
    rates = av._usd_rates()
    qs = _tx_scope(user, det)
    rows = list(qs.values("entity__region", "currency").annotate(
        n=Count("id"), f=Count("id", filter=Q(settlement_status="failed")),
        inflow=Sum("amount", filter=Q(direction="inflow", settlement_status="settled")),
        outflow=Sum("amount", filter=Q(direction="outflow", settlement_status="settled"))))
    if not rows:
        return {"facts": "No transactions in your scope.", "data": {}, "visualization": None}
    reg = defaultdict(lambda: {"n": 0, "f": 0, "net_usd": 0.0})
    for r in rows:
        g = reg[r["entity__region"]]
        g["n"] += r["n"]
        g["f"] += r["f"]
        g["net_usd"] += (float(r["inflow"] or 0) - float(r["outflow"] or 0)) * rates.get(r["currency"], 1.0)
    lines = ["By region (historical, settled flows converted to USD equivalent):"]
    for k, g in sorted(reg.items(), key=lambda kv: -kv[1]["n"]):
        lines.append(f"• {k}: {g['n']:,} transactions, {g['f'] / g['n']:.2%} failed, net flow {money(g['net_usd'], 'USD')}.")
    viz = {"type": "bar", "title": "Transactions by region", "xKey": "region",
           "series": [{"key": "transactions", "label": "Transactions"}],
           "data": [{"region": k, "transactions": g["n"]} for k, g in sorted(reg.items(), key=lambda kv: -kv[1]["n"])]}
    return {"facts": "\n".join(lines), "data": {k: dict(v) for k, v in reg.items()}, "visualization": viz}


def tool_cash_flow(user, det, direction=None):
    qs = _tx_scope(user, det).filter(settlement_status="settled")
    rows = list(qs.values("currency").annotate(
        inflow=Sum("amount", filter=Q(direction="inflow")), n_in=Count("id", filter=Q(direction="inflow")),
        outflow=Sum("amount", filter=Q(direction="outflow")), n_out=Count("id", filter=Q(direction="outflow")))
        .order_by("currency"))
    if not rows:
        return {"facts": f"No settled transactions match{_scope_label(det)}.", "data": {}, "visualization": None}
    label = {"inflow": "inflows", "outflow": "outflows"}.get(direction, "net cash flow")
    lines = [f"Settled {label}{_scope_label(det)} by currency (currencies kept separate):"]
    for r in rows:
        i, o = float(r["inflow"] or 0), float(r["outflow"] or 0)
        if direction == "inflow":
            lines.append(f"• {r['currency']}: {money(i, r['currency'])} from {r['n_in']:,} transactions")
        elif direction == "outflow":
            lines.append(f"• {r['currency']}: {money(o, r['currency'])} from {r['n_out']:,} transactions")
        else:
            lines.append(f"• {r['currency']}: in {money(i, r['currency'])}, out {money(o, r['currency'])}, "
                         f"net {money(i - o, r['currency'])}")
    rates = av._usd_rates()
    key = {"inflow": "inflow", "outflow": "outflow"}.get(direction)
    data = [{"currency": r["currency"],
             "usd": round(((float(r[key] or 0)) if key else (float(r["inflow"] or 0) - float(r["outflow"] or 0)))
                          * rates.get(r["currency"], 1.0))} for r in rows]
    viz = {"type": "bar", "title": f"Settled {label} (USD equivalent)", "xKey": "currency",
           "series": [{"key": "usd", "label": "USD eq."}], "signed": direction is None, "data": data}
    return {"facts": "\n".join(lines), "data": {"rows": [{k: (float(v) if hasattr(v, "is_finite") else v)
                                                         for k, v in r.items()} for r in rows]},
            "visualization": viz if len(data) > 1 else None}


TOOLS = {
    "help": tool_help, "general": tool_help, "summary": tool_summary, "forecast": tool_forecast,
    "alerts": tool_alerts, "surplus": tool_surplus, "counterparties": tool_counterparties,
    "upcoming": tool_upcoming, "transactions": tool_transactions, "what_if": tool_what_if,
    "settlements": tool_settlements, "settlement_causes": tool_settlement_causes,
    "monthly_trend": tool_monthly_trend, "regional_comparison": tool_regional,
    "cash_flow": lambda u, d: tool_cash_flow(u, d),
    "cash_inflow": lambda u, d: tool_cash_flow(u, d, "inflow"),
    "cash_outflow": lambda u, d: tool_cash_flow(u, d, "outflow"),
}


def run_tool(intent, user, det):
    return TOOLS.get(intent, tool_help)(user, det)
