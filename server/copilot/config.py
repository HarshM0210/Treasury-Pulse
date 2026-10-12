"""Assistant configuration (read from the environment / server/.env)."""
import os

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "60"))
OLLAMA_CONNECT_TIMEOUT = float(os.getenv("OLLAMA_CONNECT_TIMEOUT", "2"))

# auto  = use Ollama when it is reachable, otherwise answer from the deterministic summary
# ollama = same as auto (kept for clarity)
# off   = never call an LLM
LLM_MODE = os.getenv("ASSISTANT_LLM", "auto").strip().lower()

