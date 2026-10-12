"""POST /api/v1/assistant/chat/   {message, history?: [{role, content}], context?: {page, entity_id}}"""
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from treasury.permissions import IsTreasuryUser

from .config import LLM_MODE, OLLAMA_MODEL
from .llm import llm_enabled
from .service import answer_question


@api_view(["POST"])
@permission_classes([IsTreasuryUser])
def assistant_chat(request):
    message = request.data.get("message")
    if not isinstance(message, str) or not message.strip():
        return Response({"detail": "message is required."}, status=status.HTTP_400_BAD_REQUEST)
    history = request.data.get("history") or []
    if not isinstance(history, list):
        history = []
    history = [{"role": h.get("role"), "content": str(h.get("content", ""))[:1000]}
               for h in history[-8:] if isinstance(h, dict)]
    context = request.data.get("context") if isinstance(request.data.get("context"), dict) else {}
    return Response(answer_question(message, request.user, history=history, context=context))


@api_view(["GET"])
@permission_classes([IsTreasuryUser])
def assistant_status(request):
    return Response({"llm_mode": LLM_MODE, "model": OLLAMA_MODEL, "llm_available": llm_enabled()})
