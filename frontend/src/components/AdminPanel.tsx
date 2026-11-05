import { useEffect, useState } from 'react'
import { changeRole, listAudit, listUsers, setUserActive } from '../services/adminApi'
import type { AdminUser, AuditEvent } from '../types/auth'
import { formatDateTime, titleCase } from '../utils/format'

function Users({ onChanged }: { onChanged: () => void }) {
  const [rows, setRows] = useState<AdminUser[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listUsers()
      .then((data) => {
        if (!cancelled) setRows(data)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load users.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function run(action: () => Promise<unknown>) {
    setError(null)
    try {
      await action()
      onChanged()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update the user.')
    }
  }

  if (error) return <div className="error-banner">{error}</div>
  if (!rows) return <p className="muted">Loading…</p>
  return (
    <table className="ops-table">
      <thead>
        <tr><th>ID</th><th>Email</th><th>Role</th><th>Active</th><th /></tr>
      </thead>
      <tbody>
        {rows.map((u) => (
          <tr key={u.id}>
            <td>{u.id}</td>
            <td>{u.email}</td>
            <td>
              {u.role === 'customer' ? (
                'Customer'
              ) : (
                <select
                  value={u.role}
                  onChange={(e) => run(() => changeRole(u.id, e.target.value as 'support_agent' | 'admin'))}
                >
                  <option value="support_agent">Support agent</option>
                  <option value="admin">Admin</option>
                </select>
              )}
            </td>
            <td>{u.is_active ? 'Yes' : 'No'}</td>
            <td>
              <button className="secondary-button" onClick={() => run(() => setUserActive(u.id, !u.is_active))}>
                {u.is_active ? 'Deactivate' : 'Activate'}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Audit() {
  const [outcome, setOutcome] = useState('')
  const [rows, setRows] = useState<AuditEvent[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    listAudit(outcome)
      .then((data) => {
        if (!cancelled) {
          setRows(data)
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load the audit log.')
      })
    return () => {
      cancelled = true
    }
  }, [outcome])

  return (
    <>
      <label>
        Outcome{' '}
        <select value={outcome} onChange={(e) => setOutcome(e.target.value)}>
          <option value="">All</option>
          {['success', 'failure', 'denied', 'rejected'].map((o) => (
            <option key={o} value={o}>{titleCase(o)}</option>
          ))}
        </select>
      </label>
      {error && <div className="error-banner">{error}</div>}
      {!rows ? (
        <p className="muted">Loading…</p>
      ) : (
        <table className="ops-table">
          <thead>
            <tr><th>Time</th><th>User</th><th>Role</th><th>Action</th><th>Resource</th><th>Outcome</th><th>Detail</th></tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={e.id}>
                <td>{formatDateTime(e.created_at)}</td>
                <td>{e.user_id ?? '-'}</td>
                <td>{e.role ?? '-'}</td>
                <td>{e.action}</td>
                <td>{e.resource_type ? `${e.resource_type}${e.resource_id ? ` ${e.resource_id}` : ''}` : '-'}</td>
                <td>{e.outcome}</td>
                <td>{e.detail ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}

export function AdminPanel() {
  const [version, setVersion] = useState(0)
  return (
    <div className="ops-panel">
      <h2>Users</h2>
      <Users key={version} onChanged={() => setVersion((v) => v + 1)} />
      <h2>Audit log</h2>
      <Audit />
    </div>
  )
}