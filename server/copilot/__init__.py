"""AI Treasury Copilot (Pulse Assistant).

Integrated into the Treasury Pulse backend:
    POST /api/v1/assistant/chat/  ->  copilot.views.assistant_chat

Facts always come from the live database / ML outputs, scoped to the logged-in
user's entities. An LLM (Ollama, e.g. qwen3:8b) is optional and only rephrases
those facts; without it the assistant answers with the deterministic summary.
"""
