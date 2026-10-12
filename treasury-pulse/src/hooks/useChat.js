import { useCallback, useState } from 'react'
import { askAssistant } from '../services/api'

const WELCOME = {
  role: 'assistant',
  content: "Hi, I'm Pulse Assistant. Ask about cash positions, forecasts, alerts, what-if scenarios or counterparties. I answer from live data for the entities you can access.",
}

/**
 * Shared chat state for the floating widget and the AI Assistant page.
 * Backend: askAssistant() in services/api.js -> POST /api/v1/assistant/chat/.
 */
export function useChat(context = {}) {
  const [messages, setMessages] = useState([WELCOME])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const send = useCallback(
    async (text) => {
      const message = text.trim()
      if (!message || loading) return
      const history = messages.slice(1) // drop the static welcome message
      setMessages((m) => [...m, { role: 'user', content: message }])
      setLoading(true)
      setError(null)
      try {
        const r = await askAssistant({ message, history, context })
        setMessages((m) => [...m, {
          role: 'assistant', content: r.reply, visualization: r.visualization || null,
          intent: r.intent, llmUsed: !!r.llm_used, model: r.model || null,
        }])
      } catch (e) {
        setError(e?.status === 401 || e?.status === 403
          ? 'Your session has expired. Sign in again to use the assistant.'
          : 'The assistant could not be reached. Check your connection and try again.')
      } finally {
        setLoading(false)
      }
    },
    [messages, loading, context]
  )

  const reset = useCallback(() => {
    setMessages([WELCOME])
    setError(null)
  }, [])

  return { messages, loading, error, send, reset }
}
