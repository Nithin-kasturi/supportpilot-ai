import { useState } from 'react'
import { OrdersPanel } from './components/OrdersPanel'
import { ChatPage } from './pages/ChatPage'

type Tab = 'chat' | 'orders'

export default function App() {
  const [tab, setTab] = useState<Tab>('chat')
  const [ordersKey, setOrdersKey] = useState(0)

  return (
    <div className="app-shell">
      <nav className="tab-bar" role="tablist">
        <button
          role="tab"
          aria-selected={tab === 'chat'}
          className={tab === 'chat' ? 'tab active' : 'tab'}
          onClick={() => setTab('chat')}
        >
          Chat
        </button>
        <button
          role="tab"
          aria-selected={tab === 'orders'}
          className={tab === 'orders' ? 'tab active' : 'tab'}
          onClick={() => {
            setOrdersKey((k) => k + 1)
            setTab('orders')
          }}
        >
          My Orders
        </button>
      </nav>
      <div className="tab-content" hidden={tab !== 'chat'}>
        <ChatPage />
      </div>
      <div className="tab-content" hidden={tab !== 'orders'}>
        <OrdersPanel key={ordersKey} />
      </div>
    </div>
  )
}