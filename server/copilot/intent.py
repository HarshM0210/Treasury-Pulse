"""Deterministic intent and parameter extraction (no LLM involved).

detect_intent(question, entities=None, counterparties=None) -> dict

`entities` is a list of dicts {id, code, name, city, country, currency} so the user
can say "London" / "NY" / "Sao Paulo" / "entity 3"; `counterparties` is a list of
names so what-if rating shifts and counterparty questions can be resolved.
"""
import re
import unicodedata

CURRENCIES = ("USD", "EUR", "GBP", "JPY", "INR", "SGD", "CHF", "AED", "HKD", "BRL")
CITY_ALIASES = {
    "NY": ("new york", "nyc", "ny"),
    "SAO_PAULO": ("sao paulo", "sao_paulo"),
    "HK": ("hong kong", "hongkong", "hk"),
}
WHAT_IF_WORDS = ("what if", "what-if", "whatif", "scenario", "simulate", "simulation", "if we ",
                 "suppose", "stress test", "shock", "postpone", "downgrade", "delay our", "delay payments",
                 "delay outgoing", "delay all", "payment delay", "defer")
FX_WORDS = ("fx", "exchange rate", "currency", "depreciat", "appreciat", "weaken", "strengthen",
            "devalu", "eur/usd", "usd/", "/usd")
RATE_WORDS = ("interest", "bps", "basis point", "rate hike", "rate cut", "rates rise", "rates fall",
              "rate rise", "rate increase", "rate shock", "policy rate")
NEG_WORDS = ("drop", "fall", "falls", "weaken", "depreciat", "devalu", "decline", "lose", "loses", "down",
             "cut", "decrease", "lower")


def _fold(text):
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def resolve_entity(q, entities):
    """Return the entity dict mentioned in q (folded lower-case), or None."""
    if not entities:
        return None
    m = re.search(r"\bentity\s*(?:id\s*)?#?\s*(\d+)\b", q)
    if m:
        wanted = int(m.group(1))
        return next((e for e in entities if int(e["id"]) == wanted), {"id": wanted, "code": f"#{wanted}"})
    best = None
    for e in entities:
        code = str(e.get("code", "")).upper()
        names = {_fold(code).replace("_", " "), _fold(e.get("city") or ""), _fold(code)}
        names |= set(CITY_ALIASES.get(code, ()))
        for n in filter(None, names):
            # whole-word match only, so "ny" never matches inside "any"
            hit = bool(re.search(rf"\b{re.escape(n)}\b", q))
            if hit and (best is None or len(n) > best[1]):
                best = (e, len(n))
    return best[0] if best else None


def resolve_counterparty(q, counterparties):
    for name in sorted(counterparties or [], key=len, reverse=True):
        n = _fold(name)
        variants = {n, n.replace("_", " ")}
        if any(re.search(rf"\b{re.escape(v)}\b", q) for v in variants):
            return name
    return None


def _horizon(q):
    m = re.search(r"\b(\d{1,2})\s*[- ]?days?\b(?!\s*(?:late|delay|later))", q)
    if m and re.search(r"(next|coming|forecast|horizon|over|for|within|outlook)\s+(the\s+)?(next\s+)?" + m.group(1), q):
        return max(1, min(30, int(m.group(1))))
    m = re.search(r"\b(7|14|30)\s*[- ]?day", q)
    if m:
        return int(m.group(1))
    if re.search(r"\b(two weeks|fortnight)\b", q):
        return 14
    if re.search(r"\b(this|next|coming) week\b|\bweekly\b", q):
        return 7
    if re.search(r"\b(month|30 days)\b", q):
        return 30
    return None


def _what_if_params(q, counterparties):
    p = {}
    # payment delay: "delay payments by 3 days", "pay suppliers 2 days later", "3-day payment delay"
    m = (re.search(r"(?:delay|defer|push(?:ing)? back|hold)\w*\D{0,40}?(\d+)\s*(?:business\s*)?[- ]?days?", q)
         or re.search(r"(\d+)\s*[- ]?days?\s*(?:payment\s*)?(?:delay|later|late)", q))
    if m and "capex" not in q[max(0, m.start() - 25):m.end()] and "capital" not in q[max(0, m.start() - 25):m.end()]:
        p["payment_delay_days"] = int(m.group(1))
    # capex postponement: "postpone capex by 20 days"
    m = (re.search(r"(?:capex|capital (?:spend|expenditure|payments?))\D{0,40}?(\d+)\s*[- ]?days?", q)
         or re.search(r"(?:postpone|defer|delay)\w*\D{0,30}?(\d+)\s*[- ]?days?\D{0,20}(?:capex|capital)", q))
    if m:
        p["capex_postpone_days"] = int(m.group(1))
    elif re.search(r"postpone\w*\s+(?:all\s+)?(?:the\s+)?(?:capex|capital)", q):
        p["capex_postpone_days"] = 30
    negative = any(w in q for w in NEG_WORDS)
    # interest-rate shock: "+100 bps", "rates rise by 1%"
    m = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(?:bps|bp|basis points?)\b", q)
    if m:
        v = float(m.group(1))
        p["rate_shock_bps"] = int(round(-abs(v) if negative and not m.group(1).startswith("+") else v))
    pct = re.search(r"([+-]?\d+(?:\.\d+)?)\s*(?:%|percent|per cent)", q)
    if pct:
        v = float(pct.group(1))
        signed = -abs(v) if negative and not pct.group(1).startswith("+") else v
        if any(w in q for w in FX_WORDS) and not (any(w in q for w in RATE_WORDS) and "fx" not in q
                                                 and "exchange" not in q and "currency" not in q):
            p["fx_shock_pct"] = signed
        elif any(w in q for w in RATE_WORDS) and "rate_shock_bps" not in p:
            p["rate_shock_bps"] = int(round(signed * 100))
    # counterparty rating shift: "downgrade vendor_Y to D", "if client_A is rated C"
    cp = resolve_counterparty(q, counterparties)
    m = re.search(r"(?:downgrade\w*|rated?|rating\s+(?:of|to)?|re-?rate\w*|moves?\s+to|falls?\s+to)\D{0,40}?\b([abcd])\b(?:\s*rating)?", q)
    if cp and m:
        p["rating_shift"] = {"counterparty": cp, "new_rating": m.group(1).upper()}
    elif cp and "downgrade" in q:
        p["rating_shift"] = {"counterparty": cp, "new_rating": "D"}
    return p


def detect_intent(question: str, entities=None, counterparties=None) -> dict:
    original = question or ""
    q = _fold(original).strip()
    result = {
        "intent": "general", "horizon": None, "entity_id": None, "entity": None,
        "currency": None, "city": None, "direction": None, "counterparty": None,
        "what_if_params": {}, "rating": None,
    }

    ent = resolve_entity(q, entities)
    if ent:
        result["entity_id"] = int(ent["id"])
        result["entity"] = ent
        result["city"] = ent.get("city") or ent.get("code")
    cur = re.search(r"\b(" + "|".join(CURRENCIES) + r")\b", original, re.I)
    if cur:
        result["currency"] = cur.group(1).upper()
    result["horizon"] = _horizon(q)
    result["counterparty"] = resolve_counterparty(q, counterparties)
    rating = re.search(r"\b(?:rated|rating|grade)\s+([abcd])\b|\b([abcd])[- ]rated\b", q)
    if rating:
        result["rating"] = (rating.group(1) or rating.group(2)).upper()
    if "outflow" in q or "payable" in q:
        result["direction"] = "outflow"
    elif "inflow" in q or "receivable" in q or "collection" in q:
        result["direction"] = "inflow"

    params = _what_if_params(q, counterparties)
    result["what_if_params"] = params

    if any(w in q for w in WHAT_IF_WORDS) or (params and re.search(r"\b(if|delay|postpone|shock|downgrade)\b", q)):
        result["intent"] = "what_if"
    elif re.search(r"\b(cause|causes|caused|why did|why are|why were|why do|reason|reasons|root cause)\b", q) \
            and any(x in q for x in ("settlement", "failure", "failed", "fail")):
        result["intent"] = "settlement_causes"
    elif any(x in q for x in ("forecast", "projected balance", "projection", "project ", "outlook",
                              "expected balance", "will we have", "next 30", "next 14", "next 7")):
        result["intent"] = "forecast"
    elif any(x in q for x in ("alert", "shortfall", "breach", "below threshold", "liquidity risk",
                              "at risk", "short of cash", "overdraft", "emergency", "critical")):
        result["intent"] = "alerts"
    elif any(x in q for x in ("idle", "surplus", "excess cash", "deploy", "invest")):
        result["intent"] = "surplus"
    elif "counterpart" in q or result["counterparty"] or any(x in q for x in ("vendor", "client", "supplier rating")):
        result["intent"] = "counterparties"
    elif any(x in q for x in ("upcoming", "due this week", "due next", "due in", "scheduled payment",
                              "payments due", "coming up", "largest payments", "biggest payments")):
        result["intent"] = "upcoming"
    elif any(x in q for x in ("failure", "failed", "settlement", "fail rate")) and \
            not any(x in q for x in ("transactions by month", "monthly trend")):
        result["intent"] = "settlements"
    elif any(x in q for x in ("cash flow", "cashflow", "net cash", "inflows and outflows", "net flow")):
        result["intent"] = "cash_flow"
    elif "outflow" in q or "payable" in q:
        result["intent"] = "cash_outflow"
    elif "inflow" in q or "receivable" in q or "collection" in q:
        result["intent"] = "cash_inflow"
    elif any(x in q for x in ("monthly", "trend", "over time", "month by month", "per month", "by month")):
        result["intent"] = "monthly_trend"
    elif re.search(r"\b(region|regional|regions|apac|amer|emea)\b", q):
        result["intent"] = "regional_comparison"
    elif any(x in q for x in ("transaction", "transactions", "payment", "payments")):
        result["intent"] = "transactions"
    elif any(x in q for x in ("summary", "overview", "cash position", "liquidity position", "how are we doing",
                              "balance", "balances", "status", "position", "how is", "how are")):
        result["intent"] = "summary"
    elif re.search(r"\b(help|what can you do|hello|hi|hey)\b", q):
        result["intent"] = "help"
    return result
