
from rest_framework import serializers
from .models import (
    Entity,
    UserEntityAccess,
    BankAccount,
    Transaction,
    CashPosition,
    LiquidityThreshold,
    Forecast,
    Alert,
    Scenario,
    ScenarioResult,
)


class EntitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Entity
        fields = "__all__"


class UserEntityAccessSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserEntityAccess
        fields = "__all__"


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = "__all__"


def entity_code(name):
    return name.split("_", 1)[1] if name.upper().startswith("ABCBANK_") else name


class TransactionSerializer(serializers.ModelSerializer):
    entity_name = serializers.CharField(source="entity.name", read_only=True)
    entity_code = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = "__all__"

    def get_entity_code(self, obj):
        return entity_code(obj.entity.name)


class CashPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashPosition
        fields = "__all__"


class LiquidityThresholdSerializer(serializers.ModelSerializer):
    class Meta:
        model = LiquidityThreshold
        fields = "__all__"


class ForecastSerializer(serializers.ModelSerializer):
    class Meta:
        model = Forecast
        fields = "__all__"


class ForecastInputSerializer(serializers.ModelSerializer):
    class Meta:
        model = Forecast
        fields = [
            "entity",
            "forecast_date",
            "currency",
            "predicted_balance",
            "forecast_run_id",
            "lower_bound",
            "upper_bound",
            "scheduled_net",
            "predicted_net",
            "liquidity_gap",
            "risk_level",
        ]


class AlertSerializer(serializers.ModelSerializer):
    entity_name = serializers.CharField(source="entity.name", read_only=True)
    entity_code = serializers.SerializerMethodField()
    region = serializers.CharField(source="entity.region", read_only=True)

    class Meta:
        model = Alert
        fields = "__all__"

    def get_entity_code(self, obj):
        return entity_code(obj.entity.name)


class ScenarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scenario
        fields = "__all__"


class ScenarioResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ScenarioResult
        fields = "__all__"
