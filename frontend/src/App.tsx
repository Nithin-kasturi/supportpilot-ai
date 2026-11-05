import { useState } from 'react'
import { AdminPanel } from './components/AdminPanel'
import { AuthProvider } from './components/AuthProvider'
import { OrdersPanel } from './components/OrdersPanel'
import { StaffPanel } from './components/StaffPanel'
import { useAuth } from './hooks/useAuth'
import { ChatPage } from './pages/ChatPage'
import { LoginPage } from './pages/LoginPage'
import { titleCase } from './utils/format'

type Tab = 'chat' | 'orders'

function Shell() {
  const { user, status, signOut } = useAuth()
  const [tab, setTab] = useState<Tab>('chat')
  const [ordersKey, setOrdersKey] = useState(0)

  if (status === 'loading') {
    return (
      <div className="auth-screen">
        <p className="muted">Loading…</p>
      </div>
    )
  }
  if (!user) return <LoginPage />

  return (
    <div className="app-shell">
      <nav className="tab-bar" role="tablist">
        {user.role === 'customer' && (
          <>
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
          </>
        )}
        {user.role === 'support_agent' && <span className="tab active">Support console</span>}
        {user.role === 'admin' && <span className="tab active">Administration</span>}
        <span className="tab-spacer" />
        <span className="tab-user">
          {user.name} · {titleCase(user.role)}
        </span>
        <button className="tab" onClick={() => void signOut()}>
          Sign out
        </button>
      </nav>

      {user.role === 'customer' && (
        <>
          <div className="tab-content" hidden={tab !== 'chat'}>
            <ChatPage />
          </div>
          <div className="tab-content" hidden={tab !== 'orders'}>
            <OrdersPanel key={ordersKey} />
          </div>
        </>
      )}
      {user.role === 'support_agent' && (
        <div className="tab-content">
          <StaffPanel />
        </div>
      )}
      {user.role === 'admin' && (
        <div className="tab-content">
          <AdminPanel />
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  )
}