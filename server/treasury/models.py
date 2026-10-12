
from django.conf import settings
from django.db import models
from django.utils import timezone


class Entity(models.Model):
    name = models.CharField(max_length=150)
    region = models.CharField(max_length=100)
    country = models.CharField(max_length=100)

    def __str__(self):
        return self.name


class UserEntityAccess(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="entity_accesses",
    )
    entity = models.ForeignKey(
        Entity,
        on_delete=models.CASCADE,
        related_name="user_accesses",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "entity"],
                name="unique_user_entity_access",
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.entity.name}"


class BankAccount(models.Model):
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="bank_accounts"
    )
    account_number = models.CharField(max_length=100)
    currency = models.CharField(max_length=3)

    def __str__(self):
        return f"{self.account_number} ({self.currency})"


class Transaction(models.Model):
    transaction_id = models.CharField(max_length=100, unique=True)
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="transactions"
    )
    transaction_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    currency = models.CharField(max_length=3)
    direction = models.CharField(max_length=30)
    settlement_status = models.CharField(max_length=30)

    original_amount = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    origin_currency = models.CharField(max_length=3, blank=True)
    destination_currency = models.CharField(max_length=3, blank=True)
    fx_rate = models.DecimalField(
        max_digits=20, decimal_places=8, null=True, blank=True
    )

    # Fields the ML pipeline needs (counterparty risk, payment timing,
    # capex postponement, interest-rate shock). All optional so older
    # CSVs without these columns still import.
    counterparty = models.CharField(max_length=100, blank=True, default="")
    product_type = models.CharField(max_length=50, blank=True, default="")
    category = models.CharField(max_length=50, blank=True, default="")
    department = models.CharField(max_length=50, blank=True, default="")
    frequency = models.CharField(max_length=20, blank=True, default="")
    is_recurring = models.BooleanField(null=True, blank=True)
    is_cross_border = models.BooleanField(null=True, blank=True)
    interest_rate = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    maturity_date = models.DateField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["entity", "transaction_date"]),
            models.Index(fields=["counterparty"]),
        ]

    def __str__(self):
        return self.transaction_id



class CashPosition(models.Model):
    entity = models.ForeignKey(
        Entity,
        on_delete=models.CASCADE,
        related_name="cash_positions",
    )
    date = models.DateField()
    currency = models.CharField(max_length=3)

    # Existing field
    closing_balance = models.DecimalField(
        max_digits=20,
        decimal_places=4,
    )

    # New cash flow fields
    cash_flow = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=0,
    )
    daily_inflow = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=0,
    )
    daily_outflow = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=0,
    )
    net_flow = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        default=0,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["entity", "date", "currency"],
                name="unique_entity_cash_position",
            )
        ]


class LiquidityThreshold(models.Model):
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="liquidity_thresholds"
    )
    currency = models.CharField(max_length=3)
    minimum_balance = models.DecimalField(max_digits=20, decimal_places=4)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["entity", "currency"],
                name="unique_entity_liquidity_threshold",
            )
        ]


class Forecast(models.Model):
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="forecasts"
    )
    forecast_date = models.DateField()
    currency = models.CharField(max_length=3)
    predicted_balance = models.DecimalField(max_digits=20, decimal_places=4)

    forecast_run_id = models.CharField(max_length=100, blank=True)
    lower_bound = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    upper_bound = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    scheduled_net = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    predicted_net = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    liquidity_gap = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    risk_level = models.CharField(max_length=30, blank=True)


class Alert(models.Model):
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="alerts"
    )
    severity = models.CharField(max_length=30)
    liquidity_gap = models.DecimalField(max_digits=20, decimal_places=4)
    status = models.CharField(max_length=30, default="OPEN")

    # Context needed by the alert list, details panel and history log.
    currency = models.CharField(max_length=3, blank=True, default="")
    projected_balance = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    threshold = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    metric_date = models.DateField(null=True, blank=True)
    breach_probability = models.FloatField(null=True, blank=True)
    title = models.CharField(max_length=200, blank=True, default="")
    source = models.CharField(max_length=20, blank=True, default="FORECAST")
    forecast_run_id = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]


class Scenario(models.Model):
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="scenarios"
    )
    scenario_type = models.CharField(max_length=100)
    parameters = models.JSONField(default=dict, blank=True)


class ScenarioResult(models.Model):
    scenario = models.ForeignKey(
        Scenario, on_delete=models.CASCADE, related_name="results"
    )
    forecast_date = models.DateField()
    projected_balance = models.DecimalField(max_digits=20, decimal_places=4)
    currency = models.CharField(max_length=3)
    baseline_balance = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    liquidity_gap = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )


class UserRegionAccess(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="region_accesses",
    )
    region = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "region"],
                name="unique_user_region_access",
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.region}"
