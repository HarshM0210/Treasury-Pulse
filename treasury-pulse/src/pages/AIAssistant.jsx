import { RotateCcw, Sparkles } from 'lucide-react'
import { ChatBody, SUGGESTIONS } from '../components/ChatWidget'
import { useChat } from '../hooks/useChat'
import { useAuth } from '../context/AuthContext'
import { Badge, PageHeader } from '../components/ui'

const PAGE_SUGGESTIONS = [
  ...SUGGESTIONS,
  'Show the 14-day forecast for London',
  'What if EUR weakens 10% for Paris?',
  'Why did settlements fail?',
  'Compare regions',
  'Upcoming payments this week',
]

export default function AIAssistant() {
  const { role } = useAuth()
  const chat = useChat({ role, page: '/assistant' })
  return (
    <div className="mx-auto flex h-[calc(100vh-10rem)] max-w-3xl flex-col">
      <PageHeader title="AI assistant" description="Ask about positions, forecasts, alerts, what-if scenarios, counterparties and settlement history.">
        <Badge tone="violet">Live data · scoped to your entities</Badge>
        <button className="btn-outline" onClick={chat.reset}><RotateCcw size={14} /> New chat</button>
      </PageHeader>
      <div className="card flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="flex items-center gap-2.5 border-b border-line px-4 py-3">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand text-white"><Sparkles size={16} /></span>
          <p className="font-heading text-sm font-bold">Pulse Assistant</p>
        </div>
        <ChatBody chat={chat} suggestions={PAGE_SUGGESTIONS} />
      </div>
    </div>
  )
}
