
from rest_framework.routers import DefaultRouter
from .permissions import IsTreasuryUser, CanManageTreasuryData
from .views import dashboard_summary


from .views import (
    EntityViewSet,
    BankAccountViewSet,
    TransactionViewSet,
    CashPositionViewSet,
    LiquidityThresholdViewSet,
    AdminLiquidityThresholdViewSet,
    ForecastViewSet,
    AlertViewSet,
    ScenarioViewSet,
    ScenarioResultViewSet,
)

router = DefaultRouter()

router.register("entities", EntityViewSet)
router.register("bank-accounts", BankAccountViewSet)
router.register("transactions", TransactionViewSet)
router.register("cash-positions", CashPositionViewSet)
router.register("liquidity-thresholds", LiquidityThresholdViewSet)
router.register(
    "admin-liquidity-thresholds",
    AdminLiquidityThresholdViewSet,
    basename="admin-liquidity-threshold",
)
router.register("forecasts", ForecastViewSet)
router.register("alerts", AlertViewSet)
router.register("scenarios", ScenarioViewSet)
router.register("scenario-results", ScenarioResultViewSet)

from django.urls import path

from . import analytics_views as av
from copilot import views as copilot_views

urlpatterns = [
    path("dashboard/", dashboard_summary, name="dashboard-summary"),
    # ML pipeline (server/ml)
    path("ml/refresh/", av.ml_refresh, name="ml-refresh"),
    path("ml/status/", av.ml_status, name="ml-status"),
    path("analytics/summary/", av.analytics_summary, name="analytics-summary"),
    path("analytics/forecast/total/", av.analytics_forecast_total, name="analytics-forecast-total"),
    path("analytics/forecast/<int:entity_id>/", av.analytics_forecast, name="analytics-forecast"),
    path("analytics/what-if/", av.analytics_what_if, name="analytics-what-if"),
    path("analytics/counterparties/", av.analytics_counterparties, name="analytics-counterparties"),
    path("analytics/upcoming/", av.analytics_upcoming, name="analytics-upcoming"),
    path("assistant/chat/", copilot_views.assistant_chat, name="assistant-chat"),
    path("assistant/status/", copilot_views.assistant_status, name="assistant-status"),
    # must come before router.urls so it is not read as transactions/<pk>/
    path("transactions/upload/", av.transactions_upload, name="transactions-upload"),
] + router.urls
