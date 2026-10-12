# Treasury Pulse — integration & run guide

Backend: Django + DRF + Postgres (`server/`). Frontend: React + Vite (`treasury-pulse/`).
ML pipeline: `server/ml/` (Script 1 / 2 / 3). Tested end to end on Postgres 16 with the UC5 CSV.

## 1. First-time setup

```bash
# backend
cd server
source .venv/bin/activate
pip install -r requirements.txt          # adds pandas, numpy, prophet
python manage.py migrate                 # applies 0005 (ML columns on Transaction, context on Alert)
python manage.py import_transactions "UC5 - sample_transactions v3.csv"   # import + positions + forecast
python manage.py seed_demo               # demo users (run AFTER import so analysts get entity access)
python manage.py runserver               # http://127.0.0.1:8000

# frontend (second terminal)
cd treasury-pulse
npm install
npm run dev                              # http://localhost:5173  (proxies /api to :8000)
```

Already imported the CSV with the old code? Run `import_transactions` again: existing rows are kept
and the missing ML columns (counterparty, frequency, product_type, interest_rate, …) are backfilled
from the same CSV. The CSV itself is never modified.

### Demo logins (from `seed_demo`)

| Username | Password | Role | Sees |
|---|---|---|---|
| admin | admin12345 | Admin | all 10 entities, Settings, CSV upload |
| manager_emea | manager12345 | Treasury Manager | EMEA (Brussels, Dubai, London, Paris) |
| manager_apac | manager12345 | Treasury Manager | APAC |
| analyst_london | analyst12345 | Analyst | London, Paris |
| analyst_ny | analyst12345 | Analyst | NY, São Paulo |

## 2. ML pipeline

| Script | File | When it runs | Output |
|---|---|---|---|
| 1 — prepare | `ml/script1_prepare.py` | inside Script 2 / 3 (cached per data fingerprint) | cleaned transactions, R(t) per transaction, daily positions, lag distributions, FX→USD rates |
| 2 — forecast | `ml/script2_forecast.py` | **on frontend load** (`POST /api/v1/ml/refresh/`), after CSV upload, `manage.py run_forecast` | `Forecast` rows (30 days × entity) + `Alert` rows |
| 3 — what-if | `ml/script3_whatif.py` | What-if page (`POST /api/v1/analytics/what-if/`) | scenario series + KPIs, saved to `Scenario` / `ScenarioResult` |

- **Script 2 on load is cheap when nothing changed**: it compares a fingerprint of the transaction
  data with the latest `forecast_run_id` (`<as_of>_<hash>`) and returns `up_to_date`. A refit for
  10 entities takes ~3 s.
- **As-of date**: the data covers Jan–Dec 2025, so "today" is `ML_AS_OF` (env/settings):
  `auto` (default) = last transaction date − 30 days = **2025-11-28**, which leaves December as
  realised data to compare forecasts with; `latest` = last transaction date; or a fixed `YYYY-MM-DD`.
- **Model** (one Prophet per entity): target = daily settled net flow (clipped p1/p99, mean added back);
  regressors `sched_in` (Σ inflow × (1 − R(t))), `sched_out`, `month_end`, `quarter_end`;
  flat trend, weekly + monthly + quarterly seasonality; 80% band from predictive samples
  accumulated path by path. Backtest (3 origins): median position error 5.6%, band coverage 85%.
- **Bias calibration** exists (`ML_BIAS_CALIBRATION=True` or `run_forecast --calibrate`) but is off:
  it made errors larger on this dataset.
- **Counterparty risk R(t)** (`ml/risk.py`): p̂_e entity rate shrunk to the global rate, p̂_AB pair
  rate shrunk to its entity, k estimated by method of moments, p_late by frequency,
  R = 1 − (1 − p_fail)(1 − p_late). Rating bands on R: A < 0.01, B < 0.05, C < 0.18, D ≥ 0.18.
- **What-if** (Script 3): no refit. Pending transactions are copied, shocks applied (shift dates,
  rescale amounts, change R), Δ = scenario − baseline expected flows, scenario = baseline + ΣΔ,
  band shifted by the same Δ; FX translation and interest delta reported separately.
  Missing parameters = no shock = baseline.
- **Thresholds**: editing a threshold (Settings) re-classifies stored forecasts and alerts
  immediately, without a refit.
- **Opening balance**: the data has flows but no bank balances. `closing_balance` now starts from
  B0 = threshold + the year's worst cumulative drawdown (rounded up to 1,000), so the historical
  low sits exactly on the threshold. Previously it started at 0 and 5 entities sat 15–42M below zero.

## 3. Page → endpoint map

| Page | Endpoints |
|---|---|
| Login | `GET /api/auth/csrf/`, `POST /api/auth/login/`, `GET /api/auth/me/`, `POST /api/auth/logout/` |
| (every page load) | `POST /api/v1/ml/refresh/` → Script 2, `GET /api/v1/analytics/summary/`, `GET /api/v1/alerts/` |
| Overview | summary, `GET /analytics/forecast/total/`, `GET /analytics/upcoming/`, `GET /analytics/counterparties/` |
| Forecasts | `GET /api/v1/analytics/forecast/<entity_id>/?horizon=7\|14\|30` (stored Script 2 output) |
| Risk & Alerts | `GET /api/v1/alerts/`, `POST /alerts/<id>/acknowledge/`, `POST /alerts/<id>/resolve/`, summary (matrix) |
| What-if | `POST /api/v1/analytics/what-if/` → Script 3 |
| Counterparty Risk | `GET /api/v1/analytics/counterparties/` |
| Transactions | `GET /api/v1/transactions/?page&page_size&entity&currency&status&q&date_from&date_to`, `POST /api/v1/transactions/upload/` (Admin) |
| Reports | summary, alerts, `GET /analytics/upcoming/?days=2` |
| AI Assistant (page + floating chat) | `POST /api/v1/assistant/chat/` → `server/copilot`, `GET /api/v1/assistant/status/` |
| Settings | `GET/POST /api/v1/admin/users/`, `PATCH /admin/users/<id>/`, `POST /admin/users/<id>/set-active/`, `POST /api/v1/admin-liquidity-thresholds/set-currency/` |

Every analytics endpoint is scoped with `get_allowed_entities()`; out-of-scope entity IDs return 403.
API docs: http://127.0.0.1:8000/api/docs/

## 4. Integration fixes made

1. Frontend called no API (all `data/mock.js`) → `services/api.js` + `DataContext`; mock data removed.
2. Demo role picker → real session login; role comes from the server and can't be switched in the UI.
3. `corsheaders` installed but `CorsMiddleware` missing; no `CORS_ALLOW_CREDENTIALS` / `CSRF_TRUSTED_ORIGINS`
   → added; plus a Vite proxy so the browser stays on one origin (cookies + CSRF just work).
4. Role names (`ANALYST` vs `Analyst`), regions (data: EMEA/APAC/AMER vs mock NAM), currencies (CAD) → all from the API.
5. `Transaction` lacked counterparty/frequency/product_type/interest_rate/maturity_date → migration 0005 + ingestion.
6. `Alert` lacked timestamps / projected balance / breach date → migration 0005; Script 2 writes them; resolve records who/when.
7. Ingestion: one query per row (84 s) → bulk (6 s); thresholds never seeded → `ensure_default_thresholds()`.
8. `forecasts/generate` was a 7-day linear projection with HIGH/LOW → now runs Script 2.
9. `/transactions/` returned 46k rows → paginated + filters; CSV upload endpoint added.
10. Settings users: backend only listed users / changed roles → create, edit, scope, suspend added.

## 5. AI assistant (`server/copilot`)

Integrated from the standalone `ai-assistant-module`. Flow for every chat message:

1. `copilot/intent.py` — deterministic intent + parameters (no LLM): entity by name
   ("London", "New York", "Sao Paulo", "entity 3"), horizon, currency, counterparty, and
   what-if levers ("delay payments by 3 days", "postpone capex 20 days", "EUR weakens 10%",
   "+100 bps", "downgrade vendor_Y to D"). Follow-ups ("and for Paris?", "and postpone capex…")
   reuse the previous turn.
2. `copilot/live_tools.py` — computes the answer from live data **scoped to the logged-in user**:
   forecast / summary / what-if / counterparties / upcoming call the same API views in-process
   (same numbers as the pages); settlements, failure breakdown, monthly trend, regions and cash
   flows are ORM aggregations. Returns the answer text + a chart spec.
3. `copilot/llm.py` — optional: if Ollama is running, the model rephrases those facts (it is told
   to use only the supplied figures). If Ollama is not reachable the deterministic answer is
   returned immediately (retried after 60 s). The chat shows "Live data" or
   "Live data · phrased by <model>".

Settings (env / `server/.env`, all optional):

| Variable | Default | Meaning |
|---|---|---|
| `ASSISTANT_LLM` | `auto` | `auto` = use Ollama when reachable, `off` = never |
| `OLLAMA_URL` | `http://localhost:11434/api/chat` | Ollama chat endpoint |
| `OLLAMA_MODEL` | `qwen3:8b` | any pulled Ollama model |
| `OLLAMA_TIMEOUT` / `OLLAMA_CONNECT_TIMEOUT` | `60` / `2` s | read / connect timeouts |

To use the LLM: install Ollama, `ollama pull qwen3:8b`, keep `ollama serve` running, restart Django.
Tests: `python manage.py test copilot` (intent parser, no DB/LLM needed).

Changes vs the standalone module: reads the database instead of its own CSV copy; no HTTP
calls back to our own API (they returned 403 without a session); answers never depend on the
LLM being up; what-if parameter names match Script 3 (`fx_shock_pct`, `rate_shock_bps`, …);
"N days" is no longer read as a payment delay in non-what-if questions; entity names instead of IDs.

## 6. Not part of this change

- Scheduled e-mail delivery of SOD/EOD reports (reports are generated live and exportable as CSV/PDF).
