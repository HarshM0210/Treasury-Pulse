
from django.contrib import admin
from .models import UserRegionAccess

admin.site.register(UserRegionAccess)
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

admin.site.register([
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
])
