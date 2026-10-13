# Treasury Pulse

**BNP Paribas Innoversité 2026-27**

Treasury Pulse gives a treasury team a 30-day, risk-adjusted cash forecast for every legal entity, raises alerts before a
balance falls below its minimum threshold, lets the team test decisions with instant what-if scenarios, and answers
questions in plain English through an AI assistant. Every expected inflow is discounted by the measured chance that the
counterparty fails or pays late.

---

## 1. The problem

Treasury teams rebuild a cash picture every morning from bank portals and ERP exports in Excel. That process is slow,
looks only backwards, and assumes every invoice is paid in full and on time. It cannot answer the three daily questions
quickly:

| Question | How Treasury Pulse answers it |
|---|---|
| **Solvency** — will we have enough cash in this currency and entity? | 30-day forecast per entity with an 80% confidence band; alerts with the first breach date |
| **Optimisation** — where is cash sitting idle? | Deployable surplus per entity (cash that stays above threshold + 20% for the whole window) |
| **Risk mitigation** — what if FX moves or a client pays late? | What-if simulator (5 levers) and counterparty risk ratings A–D |

## 2. Features

| Page | What it does |
|---|---|
| **Overview** | Liquidity matrix for all entities in scope, open alerts, combined forecast (USD equivalent), largest upcoming flows |
| **Forecasts** | Prophet forecast per entity for 7 / 14 / 30 days, 80% band, threshold line, actual history |
| **Risk & Alerts** | Alerts by level (Emergency, Critical, Warning) with breach date and probability; acknowledge / resolve |
| **What-if** | Payment delay, capex postponement, FX shock, interest-rate shock, counterparty downgrade — baseline vs scenario in under a second |
| **Counterparty Risk** | Risk score R(t), A–D rating, failure and late-payment rates, trend, pending inflows |
| **Transactions** | Paginated, filterable list of all transactions; CSV upload (Admin) |
| **Reports** | Start-of-day / end-of-day briefing, export to CSV or PDF |
| **AI Assistant** | Chat page + floating widget; answers from live data, scoped to the user |
| **Settings** (Admin) | Users, roles, region / entity access, liquidity thresholds |

**Roles:** Admin (all entities), Treasury Manager (assigned regions), Analyst (assigned entities). Every API response
is limited to the entities the signed-in user may see.

## 3. Architecture

| Layer | Technology | Role |
|---|---|---|
| Frontend | React 18, Vite 7, Tailwind 4, Recharts, React Router 7 | Pages, charts, chat widget; one API client (`src/services/api.js`) |
| Backend | Django 5.2, Django REST Framework, drf-spectacular | Session auth, role permissions, entity scoping, REST API, OpenAPI docs |
| ML | pandas, NumPy, Prophet | Data preparation, risk scoring, forecasting, scenarios (`server/ml`) |
| AI assistant | Rule-based intent parser + live tools; optional local LLM (Ollama, `qwen3:8b`) | `server/copilot` |
| Data | PostgreSQL 16 | Transactions, positions, thresholds, forecasts, alerts, scenarios, users |

### Request flow

1. The user signs in (`POST /api/auth/login/`); Django creates a session cookie.
2. On load the frontend calls `POST /api/v1/ml/refresh/`, which runs Script 2 only if the data changed, then loads the
   summary and alerts.
3. Each request passes the gateway: middleware (CORS, session, CSRF, auth) → role permission → `get_allowed_entities`.
4. The view reads stored results or runs a script (Script 3 for what-if, copilot for chat).
5. JSON goes back and the page draws charts, tables and alerts.

## 4. ML pipeline (`server/ml`)

| Script | When it runs | What it does | Output |
|---|---|---|---|
| **Script 1 — Prepare** (`script1_prepare.py`) | Inside Scripts 2 and 3; cached by a fingerprint of the data | Reads transactions from PostgreSQL, cleans and normalises them, computes R(t) for every transaction, settlement-lag distributions, FX→USD rates, daily positions | In-memory prepared data |
| **Script 2 — Forecast** (`script2_forecast.py`) | Frontend load (`ml/refresh`), CSV upload, `manage.py run_forecast` | One Prophet model per entity; 30-day balance with 80% band; liquidity level per day; alerts | `Forecast` and `Alert` rows (one run, written atomically) |
| **Script 3 — What-if** (`script3_whatif.py`) | What-if page / assistant, on demand | Applies the shocks to pending transactions; adds the change to the stored baseline; no refit | Scenario series + KPIs; `Scenario`, `ScenarioResult` rows |

### Counterparty risk R(t) (`risk.py`, `counterparty.py`)

```
R = 1 − (1 − p_fail) · (1 − p_late)
```

- **p_fail:** failure rate of the counterparty pair, shrunk toward the entity rate, which is shrunk toward the global
  rate (empirical Bayes; strengths k ≈ 107 for entities and k ≈ 1,519 for pairs, estimated by method of moments).
- **p_late:** late-payment rate by payment frequency (≈ 0.17 for ad-hoc / daily / weekly, 0 for monthly / quarterly).
- **Rating:** A < 0.01 · B < 0.05 · C < 0.18 · D ≥ 0.18.

### Forecast model

- **Target:** daily settled net cash flow per entity (clipped at the 1st / 99th percentile).
- **Seasonality:** flat trend; weekly, monthly (30.5 days) and quarterly (91.25 days) seasonality.
- **Regressors:**
  - `sched_in`: Σ expected inflows × (1 − R), spread over the settlement-lag distribution.
  - `sched_out`: expected outflows, spread the same way.
  - `month_end` and `quarter_end` flags.
- **Band:** 300 simulated paths, accumulated into balances; the band is the 10th–90th percentile.
- **Levels** (by headroom over threshold T):
  - EMERGENCY: below T
  - CRITICAL: under 5%
  - WARNING: under 10%
  - OK: up to 20%
  - SURPLUS: above 20%
- **Deployable surplus:** lowest balance − 1.2 T.
- **Refit only when needed:** run ID = `<as-of>_<data hash>`; if it matches the stored run, Script 2 returns `up_to_date`.
  A refit for 10 entities takes about 3 s.

### What-if without retraining

```
Δ(day)            = scenario expected flows(day) − baseline expected flows(day)
scenario balance  = stored baseline balance + running total of Δ      (band shifted by the same Δ)
```

| Lever | Range | Effect on pending transactions |
|---|---|---|
| Payment delay | 0–5 days | Outflows settle later |
| Capex postponement | 0–90 days (UI 0–30) | Capex outflows move out |
| FX shock | ±50% (UI ±15%) | Cross-border outflows revalued; USD translation reported |
| Rate shock | ±500 bps (UI ±200) | Interest payments repriced; rate-bearing flows accrue |
| Counterparty rating | A–D | That counterparty's inflows re-weighted by the new R, extra delay |

### Results (backtest at 3 historical dates, all 10 entities)

| Metric | Value |
|---|---|
| Median balance error (MAPE) | 5.44% |
| Mean RMSE | 5.85M (local currency units) |
| Actuals inside the 80% band | 86.6% |

Bias calibration exists (`ML_BIAS_CALIBRATION=True` or `run_forecast --calibrate`) but is off: it increased error on this
data. A scheduled-flows-only variant is available via `ML_SCHEDULED_ONLY=True`; it also increased error (RMSE 8.06M).

## 5. AI assistant (`server/copilot`)

1. **`intent.py`:** turns the question into an intent and parameters without an LLM. It understands:
   - entity names ("London", "New York", "Sao Paulo")
   - horizons and currencies
   - counterparties
   - what-if levers ("delay payments by 3 days", "EUR weakens 10%", "+100 bps", "downgrade vendor_Y to D")

   Follow-up questions reuse the previous turn.
2. **`live_tools.py`:** computes the answer from live data scoped to the user. Forecast, what-if, counterparty and
   summary answers call the same API views as the pages, so the numbers match. Settlement, trend, region and cash-flow
   answers use ORM aggregations. It returns the answer text plus a chart spec.
3. **`llm.py`:** optional. If Ollama is running, Qwen 3 rephrases the computed facts; if not, the computed answer is
   returned immediately.

## 6. Repository layout

```
Treasury Pulse/
├── README.md
├── System Architecture.png
├── UC5 - sample_transactions v3.csv        dataset (never modified)
├── server/                                 Django backend
│   ├── config/settings.py                  DB, CORS/CSRF, ML_* and logging settings
│   ├── core/                               login, logout, me, csrf
│   ├── users/                              user admin API (roles, scope, activation)
│   ├── treasury/
│   │   ├── models.py                       Entity, Transaction, CashPosition, LiquidityThreshold,
│   │   │                                   Forecast, Alert, Scenario, ScenarioResult, access tables
│   │   ├── ingestion.py                    CSV import, thresholds, opening balances, cash positions
│   │   ├── analytics_views.py              summary, forecast, what-if, counterparties, upcoming, upload, ml/*
│   │   ├── views.py / serializers.py       transactions, alerts, thresholds, dashboard
│   │   ├── scoping.py / permissions.py     get_allowed_entities, role permissions
│   │   └── management/commands/            import_transactions, run_forecast, seed_demo
│   ├── ml/                                 script1_prepare, script2_forecast, script3_whatif,
│   │                                       risk, counterparty, rules
│   ├── copilot/                            AI assistant (intent, live_tools, llm, service, views, tests)
│   ├── requirements.txt
│   └── INTEGRATION.md                      detailed integration notes
└── treasury-pulse/                         React frontend
    ├── vite.config.js                      /api proxy to :8000
    └── src/
        ├── services/api.js                 every backend call (session cookie + CSRF header)
        ├── context/                        AuthContext (login, role), DataContext (refresh, summary, alerts)
        ├── hooks/useChat.js                assistant chat state
        ├── components/                     Layout, ChatWidget (+ chat charts), ui
        └── pages/                          Overview, Forecasts, RiskAlerts, WhatIf, CounterpartyRisk,
                                            Transactions, Reports, AIAssistant, Settings, Login
```

## 7. Setup

**Requirements:** Python 3.11+, Node 18+, PostgreSQL 14+ (tested on 16). Ollama is optional.

### Database

```bash
createuser tp -P            # choose a password
createdb treasury -O tp
```

Create `server/.env`:

```
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=True
DB_NAME=treasury
DB_USER=tp
DB_PASSWORD=<your password>
DB_HOST=127.0.0.1
DB_PORT=5432
```

### Backend

```bash
cd server
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py import_transactions "../UC5 - sample_transactions v3.csv"   # import + positions + first forecast
python manage.py seed_demo                              # demo users (run after the import)
python manage.py runserver                              # http://127.0.0.1:8000  ·  API docs: /api/docs/
```

### Frontend

```bash
cd treasury-pulse
npm install
npm run dev                                             # http://localhost:5173
```

### Optional: local LLM for the assistant

```bash
ollama pull qwen3:8b
ollama serve            # keep running, then restart Django
```

### Demo accounts

| Username | Password | Role | Sees |
|---|---|---|---|
| `admin` | `admin12345` | Admin | all 10 entities, Settings, CSV upload |
| `manager_emea` | `manager12345` | Treasury Manager | EMEA |
| `manager_apac` | `manager12345` | Treasury Manager | APAC |
| `analyst_london` | `analyst12345` | Analyst | London, Paris |
| `analyst_ny` | `analyst12345` | Analyst | New York, Sao Paulo |

## 8. Configuration

| Setting (env or `server/.env`) | Default | Meaning |
|---|---|---|
| `ML_AS_OF` | `2025-11-28` | "Today" for the pipeline. `auto` = last transaction date − 30 days; `latest` = last date. Must be before the last transaction date, or what-if has nothing to shock |
| `ML_HORIZON_DAYS` | `30` | Forecast horizon |
| `ML_CI_LEVEL` | `0.80` | Confidence band |
| `ML_UNCERTAINTY_SAMPLES` | `300` | Simulated paths for the band |
| `ML_BIAS_CALIBRATION` | `False` | Bias correction (off: it hurt accuracy) |
| `ASSISTANT_LLM` | `auto` | `auto` = use Ollama when reachable, `off` = never |
| `OLLAMA_URL` / `OLLAMA_MODEL` | `http://localhost:11434/api/chat` / `qwen3:8b` | Local LLM |

After changing `ML_AS_OF` or thresholds in bulk, rebuild: `python manage.py run_forecast --force`.

## 9. API (ML-related)

All under `/api/v1/`, session-authenticated and scoped to the user's entities.

| Endpoint | What it does |
|---|---|
| `POST ml/refresh/` | Runs Script 2 (refits only if data changed); called on page load |
| `GET ml/status/` | Whether the stored run matches the current data |
| `GET analytics/summary/` | Per-entity balance, threshold, projected low, level, first breach date |
| `GET analytics/forecast/<entity_id>/?horizon=7\|14\|30` | Stored forecast with band and recent history |
| `GET analytics/forecast/total/` | Combined forecast in USD equivalent |
| `POST analytics/what-if/` | Runs Script 3: `{entity_id, horizon, parameters}` |
| `GET analytics/counterparties/` | Ratings, R(t), failure / late rates |
| `GET analytics/upcoming/?days=7` | Largest scheduled flows |
| `GET alerts/`, `POST alerts/<id>/acknowledge/`, `/resolve/` | Alerts from Script 2 |
| `POST transactions/upload/` | Admin CSV import → forced Script 2 refit |
| `POST admin-liquidity-thresholds/set-currency/` | Change a threshold; re-labels stored results |
| `POST assistant/chat/` | AI assistant `{message, history, context}` |

Full schema: `http://127.0.0.1:8000/api/docs/`.

## 10. Testing

| Test | Command | Result |
|---|---|---|
| Assistant intent parser (12 unit tests) | `python manage.py test copilot` | all pass |
| End-to-end API suite (auth, forecast, alerts, what-if, counterparties, upload, users, assistant, out-of-scope access) | run against a live server | all checks pass |
| Forecast backtest (3 origins × 10 entities) | `run_forecast` backtest | MAPE 5.44%, 86.6% coverage |

## 11. Data and assumptions

- 46,006 transactions, 10 entities, 10 currencies, 25 counterparties, Jan–Dec 2025. The CSV is never modified.
- The data has flows but no bank balances. The opening balance B0 = threshold + the year's worst cumulative drawdown
  (rounded up to 1,000), so the historical low sits on the threshold.
- Amounts stay in their own currency; totals labelled "USD equivalent" use FX rates derived from the data.
- As-of 28 Nov 2025 leaves December as realised data to compare forecasts against.

## 12. Limitations and next steps

- One year of history: no yearly seasonality; opening balances are reconstructed.
- No live bank / ERP connector yet. The next step is to ingest bank statements (e.g. camt.053) and open invoices directly.
- Scheduled e-mail delivery of reports is not built; reports are generated on demand.
