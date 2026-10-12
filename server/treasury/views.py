from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from .permissions import IsTreasuryUser, CanManageTreasuryData
from rest_framework import viewsets
from django.db.models import OuterRef, Subquery, Sum, Max
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db.models import Q
from rest_framework.pagination import PageNumberPagination

from ml.script2_forecast import reclassify
from ml.script2_forecast import run as run_forecast

from django.utils import timezone
from rest_framework.decorators import action
from rest_framework.response import Response

from django.db import transaction

from .models import LiquidityThreshold

from .models import (
    Entity,
    BankAccount,
    Transaction,
    CashPosition,
    LiquidityThreshold,
    Forecast,
    Alert,
    Scenario,
    ScenarioResult,
)
from .serializers import (
    EntitySerializer,
    BankAccountSerializer,
    TransactionSerializer,
    CashPositionSerializer,
    LiquidityThresholdSerializer,
    ForecastSerializer,
    ForecastInputSerializer,
    AlertSerializer,
    ScenarioSerializer,
    ScenarioResultSerializer,
)
from .permissions import IsTreasuryUser
from .scoping import get_allowed_entities


class ReadOnlyTreasuryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsTreasuryUser]
    entity_lookup = "entity"

    def get_queryset(self):
        queryset = super().get_queryset()
        allowed_entities = get_allowed_entities(self.request.user)

        if self.entity_lookup == "__self__":
            return queryset.filter(
                pk__in=allowed_entities.values("pk")
            )

        return queryset.filter(
            **{f"{self.entity_lookup}__in": allowed_entities}
        )


class EntityViewSet(ReadOnlyTreasuryViewSet):
    queryset = Entity.objects.all()
    serializer_class = EntitySerializer
    entity_lookup = "__self__"


class BankAccountViewSet(ReadOnlyTreasuryViewSet):
    queryset = BankAccount.objects.all()
    serializer_class = BankAccountSerializer


class TransactionPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 500


class TransactionViewSet(ReadOnlyTreasuryViewSet):
    """Paginated (46k rows). Filters: entity, currency, status, direction,
    counterparty, q (id / counterparty / entity), date_from, date_to, ordering."""
    queryset = Transaction.objects.select_related("entity").all()
    serializer_class = TransactionSerializer
    pagination_class = TransactionPagination

    def get_queryset(self):
        qs = super().get_queryset()
        p = self.request.query_params
        if p.get("entity"):
            qs = qs.filter(entity_id=p["entity"])
        if p.get("currency"):
            qs = qs.filter(currency=p["currency"].upper())
        if p.get("status"):
            qs = qs.filter(settlement_status=p["status"].lower())
        if p.get("direction"):
            qs = qs.filter(direction=p["direction"].lower())
        if p.get("counterparty"):
            qs = qs.filter(counterparty=p["counterparty"])
        if p.get("date_from"):
            qs = qs.filter(transaction_date__gte=p["date_from"])
        if p.get("date_to"):
            qs = qs.filter(transaction_date__lte=p["date_to"])
        if p.get("q"):
            q = p["q"].strip()
            qs = qs.filter(Q(transaction_id__icontains=q) | Q(counterparty__icontains=q) | Q(entity__name__icontains=q))
        ordering = p.get("ordering", "-transaction_date")
        allowed = {"transaction_date", "-transaction_date", "amount", "-amount", "due_date", "-due_date"}
        return qs.order_by(ordering if ordering in allowed else "-transaction_date", "transaction_id")


class CashPositionViewSet(ReadOnlyTreasuryViewSet):
    queryset = CashPosition.objects.all()
    serializer_class = CashPositionSerializer


class LiquidityThresholdViewSet(ReadOnlyTreasuryViewSet):
    queryset = LiquidityThreshold.objects.all()
    serializer_class = LiquidityThresholdSerializer


class AdminLiquidityThresholdViewSet(viewsets.ModelViewSet):
    queryset = LiquidityThreshold.objects.all()
    serializer_class = LiquidityThresholdSerializer
    permission_classes = [CanManageTreasuryData]

    def get_queryset(self):
        queryset = super().get_queryset()
        allowed_entities = get_allowed_entities(self.request.user)
        return queryset.filter(entity__in=allowed_entities)

    def perform_update(self, serializer):
        instance = serializer.save()
        reclassify([instance.entity_id])

    def perform_create(self, serializer):
        instance = serializer.save()
        reclassify([instance.entity_id])

    @action(detail=False, methods=["post"], url_path="set-currency")
    def set_currency(self, request):
        """Set the minimum balance for every entity in one currency (Settings page)."""
        currency = str(request.data.get("currency", "")).upper()
        try:
            value = Decimal(str(request.data.get("minimum_balance")))
        except (InvalidOperation, TypeError):
            return Response({"detail": "minimum_balance must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        if not currency or value <= 0:
            return Response({"detail": "currency and a positive minimum_balance are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        rows = self.get_queryset().filter(currency=currency)
        entity_ids = list(rows.values_list("entity_id", flat=True))
        if not entity_ids:
            return Response({"detail": f"No entities use {currency}."}, status=status.HTTP_404_NOT_FOUND)
        rows.update(minimum_balance=value)
        reclassify(entity_ids)
        return Response({"currency": currency, "minimum_balance": float(value), "entities_updated": len(entity_ids)})


class ForecastViewSet(ReadOnlyTreasuryViewSet):
    queryset = Forecast.objects.all()
    serializer_class = ForecastSerializer

    @action(detail=False, methods=["post"], url_path="store")
    def store(self, request):
        serializer = ForecastInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        entity = serializer.validated_data["entity"]
        allowed_entities = get_allowed_entities(request.user)

        if not allowed_entities.filter(id=entity.id).exists():
            return Response(
                {"detail": "You do not have access to this entity."},
                status=status.HTTP_403_FORBIDDEN,
            )

        forecast, created = Forecast.objects.update_or_create(
            entity=entity,
            currency=serializer.validated_data["currency"],
            forecast_date=serializer.validated_data["forecast_date"],
            defaults={
                key: value
                for key, value in serializer.validated_data.items()
                if key != "entity"
            },
        )

        return Response(
            ForecastSerializer(forecast).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


    @action(detail=False, methods=["post"])
    def generate(self, request):
        """Run ML Script 2 (Prophet, 30 days, all entities) and store results."""
        try:
            result = run_forecast(force=True)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            "message": "Forecast generation completed.",
            "forecast_run_id": result["forecast_run_id"],
            "forecasts_generated": sum(1 for _ in result.get("entities", {})) * settings.ML_HORIZON_DAYS,
            "elapsed_seconds": result.get("elapsed_seconds"),
        })


class AlertViewSet(ReadOnlyTreasuryViewSet):
    queryset = Alert.objects.select_related("entity").order_by("-created_at")
    serializer_class = AlertSerializer

    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        alert = self.get_object()
        alert.status = "ACKNOWLEDGED"
        alert.save(update_fields=["status", "updated_at"])

        return Response({
            "message": "Alert acknowledged successfully.",
            "alert_id": alert.id,
            "status": alert.status,
        })

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        alert = self.get_object()
        alert.status = "RESOLVED"
        alert.resolved_at = timezone.now()
        alert.resolved_by = request.user.username
        alert.save(update_fields=["status", "resolved_at", "resolved_by", "updated_at"])

        return Response({
            "message": "Alert resolved successfully.",
            "alert_id": alert.id,
            "status": alert.status,
        })



class ScenarioViewSet(ReadOnlyTreasuryViewSet):
    queryset = Scenario.objects.all()
    serializer_class = ScenarioSerializer


class ScenarioResultViewSet(ReadOnlyTreasuryViewSet):
    queryset = ScenarioResult.objects.all()
    serializer_class = ScenarioResultSerializer
    entity_lookup = "scenario__entity"


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsTreasuryUser])
def dashboard_summary(request):
    allowed_entities = get_allowed_entities(request.user)

    latest_position_date = (
        CashPosition.objects
        .filter(
            entity_id=OuterRef("entity_id"),
            currency=OuterRef("currency"),
        )
        .order_by("-date")
        .values("date")[:1]
    )

    positions = CashPosition.objects.filter(
        entity__in=allowed_entities,
        date=Subquery(latest_position_date),
    )

    latest_date = positions.aggregate(
        latest_date=Max("date")
    )["latest_date"]

    currency_totals = positions.values("currency").annotate(
        closing_balance=Sum("closing_balance"),
        daily_inflow=Sum("daily_inflow"),
        daily_outflow=Sum("daily_outflow"),
        net_flow=Sum("net_flow"),
    ).order_by("currency")

    open_alert_count = Alert.objects.filter(
        entity__in=allowed_entities,
        status="OPEN",
    ).count()

    entity_positions = positions.values(
        "entity_id",
        "entity__name",
        "currency",
        "date",
    ).annotate(
        closing_balance=Sum("closing_balance"),
        daily_inflow=Sum("daily_inflow"),
        daily_outflow=Sum("daily_outflow"),
        net_flow=Sum("net_flow"),
    ).order_by("entity__name", "currency")

    return Response({
        "as_of": latest_date,
        "currency_totals": list(currency_totals),
        "open_alert_count": open_alert_count,
        "entity_positions": list(entity_positions),
    })
