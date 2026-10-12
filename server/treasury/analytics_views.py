"""
API endpoints backed by the ML pipeline (server/ml).

    POST /api/v1/ml/refresh/                 Script 2 (skips if forecasts are current)
    GET  /api/v1/ml/status/                  latest run + whether it is current
    GET  /api/v1/analytics/summary/          entity rows for Overview / Alert matrix / Reports
    GET  /api/v1/analytics/forecast/<id>/    history + stored forecast for one entity (Script 2 output)
    GET  /api/v1/analytics/forecast/total/   USD-equivalent total of the allowed entities
    POST /api/v1/analytics/what-if/          Script 3
    GET  /api/v1/analytics/counterparties/   counterparty risk (agreed R(t) algorithm)
    GET  /api/v1/analytics/upcoming/         largest pending payments in the next N days
    POST /api/v1/transactions/upload/        CSV import → positions → Script 2 (Admin)
"""
import logging
import os
import tempfile
from datetime import timedelta

import pandas as pd
from django.db.models import Q, Sum
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from ml import rules
from ml.script1_prepare import invalidate_cache, parse_run_id, prepare
from ml.script2_forecast import is_up_to_date, latest_run_id
from ml.script2_forecast import run as run_forecast

from .defaults import default_threshold
from .models import Alert, CashPosition, Forecast, LiquidityThreshold, Transaction
from .permissions import IsAdminRole, IsTreasuryUser
from .scoping import get_allowed_entities

log = logging.getLogger("ml")


def _code(name):
    return name.split("_", 1)[1] if name.upper().startswith(("ABCBANK_",)) else name


def _f(x):
    return None if x is None else float(x)


def _as_of_and_run():
    run_id = latest_run_id()
    return (parse_run_id(run_id) if run_id else None), run_id


def _usd_rates():
    try:
        return prepare().usd_rate
    except ValueError:
        return {"USD": 1.0}


def _position_on(entity_id, currency, day):
    cp = (CashPosition.objects.filter(entity_id=entity_id, currency=currency, date__lte=day)
          .order_by("-date").values_list("closing_balance", flat=True).first())
    return _f(cp)


# ─── ML control ────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsTreasuryUser])
def ml_refresh(request):
    """Called by the frontend on load. Fits models only when the data changed."""
    force = bool(request.data.get("force")) if hasattr(request, "data") else False
    if force and request.user.profile.role != "ADMIN":
        force = False
    try:
        result = run_forecast(force=force)
    except ValueError as exc:
        return Response({"status": "no_data", "detail": str(exc)}, status=status.HTTP_200_OK)
    result.pop("risk_model", None)
    return Response(result)


@api_view(["GET"])
@permission_classes([IsTreasuryUser])
def ml_status(request):
    fresh, expected_run = is_up_to_date()
    return Response({"latest_run_id": latest_run_id(), "current_run_id": expected_run, "up_to_date": fresh})


# ─── summary / forecasts ───────────────────────────────────────────────

def _entity_rows(user, horizon=30):
    as_of, run_id = _as_of_and_run()
    rates = _usd_rates()
    entities = list(get_allowed_entities(user).order_by("region", "name"))
    thresholds = {(t.entity_id, t.currency): float(t.minimum_balance) for t in
                  LiquidityThreshold.objects.filter(entity__in=entities)}
    rows = []
    for e in entities:
        forecasts = list(Forecast.objects.filter(entity=e).order_by("forecast_date")[:horizon])
        currency = forecasts[0].currency if forecasts else (
            Transaction.objects.filter(entity=e).values_list("currency", flat=True).first() or "USD")
        threshold = thresholds.get((e.id, currency), float(default_threshold(currency)))
        balance = _position_on(e.id, currency, as_of) if as_of else None
        row = {
            "id": e.id, "code": _code(e.name), "name": e.name, "region": e.region, "country": e.country,
            "currency": currency, "threshold": threshold, "usd_rate": rates.get(currency, 1.0),
            "balance": balance, "as_of": str(as_of.date()) if as_of else None,
            "projected": None, "projected_min": None, "projected_min_date": None,
            "gap": None, "level": None, "status": None, "first_breach_date": None,
            "inflow_30d": 0.0, "outflow_30d": 0.0, "forecast_run_id": run_id,
        }
        if forecasts:
            low = min(forecasts, key=lambda f: f.predicted_balance)
            levels = [f.risk_level for f in forecasts]
            worst = rules.worst(levels + ([rules.classify(balance, threshold)] if balance is not None else []))
            breach = next((f.forecast_date for f in forecasts if f.risk_level in rules.ALERT_LEVELS), None)
            row.update({
                "projected": _f(forecasts[-1].predicted_balance),
                "projected_min": _f(low.predicted_balance),
                "projected_min_date": str(low.forecast_date),
                "gap": _f(low.predicted_balance) - threshold,
                "level": worst, "status": worst.lower(),
                "first_breach_date": str(breach) if breach else None,
                "deployable_surplus": rules.deployable_surplus(low.predicted_balance, threshold),
            })
            flows = (Transaction.objects
                     .filter(entity=e, transaction_date__gt=as_of, due_date__lte=as_of + timedelta(days=horizon))
                     .aggregate(inflow=Sum("amount", filter=Q(direction="inflow")),
                                outflow=Sum("amount", filter=Q(direction="outflow"))))
            row["inflow_30d"] = _f(flows["inflow"]) or 0.0
            row["outflow_30d"] = _f(flows["outflow"]) or 0.0
        rows.append(row)
    return rows, as_of, run_id, rates


@api_view(["GET"])
@permission_classes([IsTreasuryUser])
def analytics_summary(request):
    horizon = int(request.query_params.get("horizon", 30))
    rows, as_of, run_id, rates = _entity_rows(request.user, horizon)
    allowed = [r["id"] for r in rows]
    open_alerts = Alert.objects.filter(entity_id__in=allowed, status__in=["OPEN", "ACKNOWLEDGED"]).count()
    return Response({
        "as_of": str(as_of.date()) if as_of else None,
        "forecast_run_id": run_id,
        "horizon": horizon,
        "usd_rates": rates,
        "regions": sorted({r["region"] for r in rows}),
        "currencies": sorted({r["currency"] for r in rows}),
        "open_alerts": open_alerts,
        "entities": rows,
    })


def _history(entity_id, currency, as_of, days):
    start = as_of - timedelta(days=days)
    cps = list(CashPosition.objects.filter(entity_id=entity_id, currency=currency, date__lte=as_of)
               .order_by("-date").values("date", "closing_balance")[: days + 40])
    if not cps:
        return []
    s = pd.Series({pd.Timestamp(c["date"]): float(c["closing_balance"]) for c in cps}).sort_index()
    s = s.reindex(pd.date_range(min(s.index.min(), pd.Timestamp(start)), as_of, freq="D")).ffill().dropna()
    s = s[s.index >= pd.Timestamp(start)]
    return [{"date": str(d.date()), "actual": round(v, 2)} for d, v in s.items()]


@api_view(["GET"])
@permission_classes([IsTreasuryUser])
def analytics_forecast(request, entity_id):
    entity = get_allowed_entities(request.user).filter(id=entity_id).first()
    if entity is None:
        return Response({"detail": "You do not have access to this entity."}, status=status.HTTP_403_FORBIDDEN)
    horizon = int(request.query_params.get("horizon", 30))
    history_days = int(request.query_params.get("history", 30))
    as_of, run_id = _as_of_and_run()
    forecasts = list(Forecast.objects.filter(entity=entity).order_by("forecast_date")[:horizon])
    if not forecasts or as_of is None:
        return Response({"detail": "No forecast yet. Call /ml/refresh/ first."}, status=status.HTTP_404_NOT_FOUND)
    currency = forecasts[0].currency
    threshold = float(LiquidityThreshold.objects.filter(entity=entity, currency=currency)
                      .values_list("minimum_balance", flat=True).first() or default_threshold(currency))
    history = _history(entity.id, currency, as_of.date(), history_days)
    points = [{
        "date": str(f.forecast_date), "forecast": _f(f.predicted_balance),
        "lower": _f(f.lower_bound), "upper": _f(f.upper_bound),
        "scheduled_net": _f(f.scheduled_net), "predicted_net": _f(f.predicted_net),
        "liquidity_gap": _f(f.liquidity_gap), "risk_level": f.risk_level,
    } for f in forecasts]
    balance = history[-1]["actual"] if history else None
    low = min(points, key=lambda p: p["forecast"])
    return Response({
        "entity": {"id": entity.id, "code": _code(entity.name), "name": entity.name, "region": entity.region,
                   "currency": currency, "threshold": threshold},
        "as_of": str(as_of.date()), "forecast_run_id": run_id, "horizon": len(points),
        "balance": balance, "projected": points[-1]["forecast"],
        "projected_min": low["forecast"], "projected_min_date": low["date"],
        "lowest_lower_bound": min(p["lower"] for p in points if p["lower"] is not None),
        "worst_level": rules.worst(p["risk_level"] for p in points),
        "history": history, "forecast": points,
    })


@api_view(["GET"])
@permission_classes([IsTreasuryUser])
def analytics_forecast_total(request):
    """USD-equivalent sum of history and forecast across the user's entities.
    Band = sum of entity bands (an approximation; entity errors are not perfectly correlated)."""
    horizon = int(request.query_params.get("horizon", 30))
    history_days = int(request.query_params.get("history", 30))
    as_of, run_id = _as_of_and_run()
    if as_of is None:
        return Response({"detail": "No forecast yet."}, status=status.HTTP_404_NOT_FOUND)
    rates = _usd_rates()
    hist, fut, threshold = {}, {}, 0.0
    for e in get_allowed_entities(request.user):
        fcs = list(Forecast.objects.filter(entity=e).order_by("forecast_date")[:horizon])
        if not fcs:
            continue
        ccy = fcs[0].currency
        rate = rates.get(ccy, 1.0)
        threshold += rate * float(LiquidityThreshold.objects.filter(entity=e, currency=ccy)
                                  .values_list("minimum_balance", flat=True).first() or default_threshold(ccy))
        for h in _history(e.id, ccy, as_of.date(), history_days):
            hist[h["date"]] = hist.get(h["date"], 0.0) + h["actual"] * rate
        for f in fcs:
            d = str(f.forecast_date)
            acc = fut.setdefault(d, [0.0, 0.0, 0.0])
            acc[0] += float(f.predicted_balance) * rate
            acc[1] += float(f.lower_bound if f.lower_bound is not None else f.predicted_balance) * rate
            acc[2] += float(f.upper_bound if f.upper_bound is not None else f.predicted_balance) * rate
    return Response({
        "as_of": str(as_of.date()), "currency": "USD", "threshold": threshold,
        "history": [{"date": d, "actual": round(v, 2)} for d, v in sorted(hist.items())],
        "forecast": [{"date": d, "forecast": round(v[0], 2), "lower": round(v[1], 2), "upper": round(v[2], 2)}
                     for d, v in sorted(fut.items())],
    })


# ─── what-if (Script 3) ────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsTreasuryUser])
def analytics_what_if(request):
    from ml.script3_whatif import run_what_if

    try:
        entity_id = int(request.data.get("entity_id"))
    except (TypeError, ValueError):
        return Response({"detail": "entity_id is required."}, status=status.HTTP_400_BAD_REQUEST)
    if not get_allowed_entities(request.user).filter(id=entity_id).exists():
        return Response({"detail": "You do not have access to this entity."}, status=status.HTTP_403_FORBIDDEN)
    try:
        result = run_what_if(entity_id, horizon=request.data.get("horizon"),
                             params=request.data.get("parameters") or {})
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(result)


# ─── counterparties / upcoming ─────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsTreasuryUser])
def analytics_counterparties(request):
    from ml.counterparty import counterparty_summary

    allowed = list(get_allowed_entities(request.user).values_list("id", flat=True))
    try:
        return Response(counterparty_summary(entity_ids=allowed))
    except ValueError as exc:
        return Response({"detail": str(exc), "counterparties": []})


@api_view(["GET"])
@permission_classes([IsTreasuryUser])
def analytics_upcoming(request):
    days = int(request.query_params.get("days", 7))
    limit = int(request.query_params.get("limit", 8))
    as_of, _ = _as_of_and_run()
    if as_of is None:
        return Response({"as_of": None, "events": []})
    rates = _usd_rates()
    levels = {}
    for f in Forecast.objects.values("entity_id", "risk_level"):
        levels[f["entity_id"]] = rules.worst([levels.get(f["entity_id"], "SURPLUS"), f["risk_level"]])
    qs = (Transaction.objects
          .filter(entity__in=get_allowed_entities(request.user), transaction_date__gt=as_of,
                  due_date__gt=as_of, due_date__lte=as_of + timedelta(days=days))
          .select_related("entity"))
    events = sorted(qs, key=lambda t: -float(t.amount) * rates.get(t.currency, 1.0))[:limit]
    return Response({"as_of": str(as_of.date()), "events": [{
        "id": t.transaction_id, "date": str(t.due_date), "entity_id": t.entity_id, "entity": _code(t.entity.name),
        "description": f"{t.product_type.replace('_', ' ').capitalize() or 'Payment'} · {t.counterparty}",
        "amount": float(t.amount), "currency": t.currency, "direction": t.direction,
        "usd_amount": float(t.amount) * rates.get(t.currency, 1.0),
        "status": (levels.get(t.entity_id) or "OK").lower(),
    } for t in events]})


# ─── CSV upload ────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAdminRole])
@parser_classes([MultiPartParser, FormParser])
def transactions_upload(request):
    from .ingestion import ingest_csv

    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "Attach a CSV file in the 'file' field."}, status=status.HTTP_400_BAD_REQUEST)
    if not upload.name.lower().endswith(".csv"):
        return Response({"detail": "Only .csv files are supported."}, status=status.HTTP_400_BAD_REQUEST)

    fd, path = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(fd, "wb") as out:
            for chunk in upload.chunks():
                out.write(chunk)
        stats = ingest_csv(path)
    except ValueError as exc:
        return Response({"status": "invalid", "detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    finally:
        os.remove(path)

    invalidate_cache()
    forecast = run_forecast(force=stats["new_transactions"] > 0 or stats.get("ml_fields_backfilled", 0) > 0)
    forecast.pop("risk_model", None)
    return Response({"status": "imported", "filename": upload.name, "stats": stats, "forecast": forecast})
