"""Assistant orchestration: detect intent -> compute facts with live tools -> optionally phrase with the LLM.

answer_question(question, user, history=None, context=None) ->
    {"reply", "intent", "params", "data", "visualization", "source", "llm_used", "model"}
"""
import json
import logging
import re

from .config import OLLAMA_MODEL
from .intent import detect_intent
from .live_tools import ToolError, counterparty_names, entity_directory, run_tool
from .llm import LLMUnavailable, ask_llm

log = logging.getLogger("ml")

FOLLOW_UP_INTENTS = {"forecast", "what_if", "alerts", "settlements", "settlement_causes", "monthly_trend",
                     "counterparties", "upcoming", "cash_flow", "cash_inflow", "cash_outflow", "transactions",
                     "summary", "surplus"}
NO_LLM_INTENTS = {"help"}


def _previous(history, entities, cps):
    """Intent/parameters of the last user turn, for follow-ups like 'and for London?'."""
    for turn in reversed(history or []):
        if turn.get("role") == "user" and turn.get("content"):
            return detect_intent(turn["content"], entities, cps)
    return None


def _merge_follow_up(det, prev, context, question=""):
    has_new_slot = det["entity_id"] or det["horizon"] or det["what_if_params"] or det["counterparty"] or det["currency"]
    if prev and det["intent"] in ("general", "summary", "help") and has_new_slot and prev["intent"] in FOLLOW_UP_INTENTS:
        det["intent"] = prev["intent"]
    if prev and det["intent"] == prev["intent"]:
        # A follow-up that names a new entity starts fresh; otherwise carry the earlier slots over.
        keys = ("entity_id", "entity") if det.get("entity_id") is None else ()
        if det.get("entity_id") is None:
            keys += ("horizon", "currency", "counterparty", "direction")
        for key in keys:
            if det.get(key) in (None, {}) and prev.get(key) is not None:
                det[key] = prev[key]
        if det["intent"] == "what_if":
            additive = re.match(r"\s*(and|also|plus|add|on top|as well)\b", question, re.I)
            if not det["what_if_params"]:
                det["what_if_params"] = prev.get("what_if_params") or {}
            elif additive and det.get("entity_id") == prev.get("entity_id"):
                det["what_if_params"] = {**(prev.get("what_if_params") or {}), **det["what_if_params"]}
    if det.get("entity_id") is None and (context or {}).get("entity_id"):
        try:
            det["entity_id"] = int(context["entity_id"])
        except (TypeError, ValueError):
            pass
    return det


def answer_question(question, user, history=None, context=None):
    question = (question or "").strip()[:1000]
    base = {"intent": "general", "params": {}, "data": None, "visualization": None,
            "source": "live", "llm_used": False, "model": None}
    if not question:
        return {**base, "reply": "Please enter a question."}

    entities = entity_directory()
    cps = counterparty_names()
    det = detect_intent(question, entities, cps)
    det = _merge_follow_up(det, _previous(history, entities, cps), context, question)
    intent = det["intent"]
    params = {k: det[k] for k in ("entity_id", "horizon", "currency", "counterparty", "direction", "rating")
              if det.get(k) is not None}
    if det.get("what_if_params"):
        params["what_if"] = det["what_if_params"]

    try:
        out = run_tool(intent, user, det)
    except ToolError as exc:
        return {**base, "intent": intent, "params": params, "reply": str(exc)}
    except ValueError as exc:  # parameter validation from Script 3
        return {**base, "intent": intent, "params": params, "reply": f"I couldn't run that: {exc}"}
    except Exception:  # never leak a stack trace into the chat
        log.exception("assistant tool failed for intent %s", intent)
        return {**base, "intent": intent, "params": params,
                "reply": "Something went wrong while reading the treasury data. Please try again or rephrase."}

    if out.get("needs_input"):
        return {**base, "intent": intent, "params": params, "reply": out["needs_input"]}

    reply, llm_used = out["facts"], False
    if intent not in NO_LLM_INTENTS:
        try:
            context_json = json.dumps({"intent": intent, "evidence": out.get("data")}, default=str)[:6000]
            reply = ask_llm(question, out["facts"], context_json, history)
            llm_used = True
        except LLMUnavailable as exc:
            log.debug("LLM not used: %s", exc)

    viz = out.get("visualization")
    if viz and len(viz.get("data") or []) < 2:
        viz = None
    return {**base, "intent": intent, "params": params, "reply": reply, "facts": out["facts"],
            "data": out.get("data"), "visualization": viz,
            "llm_used": llm_used, "model": OLLAMA_MODEL if llm_used else None}
