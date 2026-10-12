# Treasury Pulse — Frontend

AI-powered short-term liquidity manager. React + Vite + Tailwind + Recharts, connected to the Django API in `../server`.

## Run
```bash
npm install
npm run dev        # http://localhost:5173 — /api is proxied to http://127.0.0.1:8000
```
Start the backend first (see `server/INTEGRATION.md`). Log in with a seeded account, e.g. `admin` / `admin12345`.
To point at another API host, set `VITE_API_PROXY` (dev proxy) or `VITE_API_BASE_URL` (direct calls; then CORS applies).

## Structure
- `src/services/api.js` — every backend call (session cookie + CSRF header).
- `src/context/AuthContext.jsx` — real login; role comes from the server.
- `src/context/DataContext.jsx` — on sign-in runs ML Script 2 (`POST /api/v1/ml/refresh/`, skips if current), then loads the entity summary and alerts.
- `src/lib/format.js` — money/date formatting, role policy.
- Pages: Forecasts and Risk & Alerts read stored Script 2 results; What-if calls Script 3; Counterparty Risk uses the R(t) algorithm.

## AI chatbot
`askAssistant({ message, history, context })` in `src/services/api.js` is still the integration point (no backend endpoint yet). Return `{ reply: string }`.

## Currency rule
Amounts stay in their own currency. Totals labelled "USD equivalent" use FX rates derived from the transaction data by the backend.
