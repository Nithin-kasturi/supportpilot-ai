import type { AdminUser, AuditEvent, StaffRefund, StaffTicket } from '../types/auth'
import { getJson, sendJson } from './http'

export const listStaffTickets = () => getJson<StaffTicket[]>('/api/staff/tickets')
export const updateTicketStatus = (reference: string, status: string) =>
  sendJson<StaffTicket>('PATCH', `/api/staff/tickets/${encodeURIComponent(reference)}/status`, { status })
export const listStaffRefunds = () => getJson<StaffRefund[]>('/api/staff/refund-requests')
export const reviewRefund = (reference: string, decision: 'approve' | 'reject') =>
  sendJson<StaffRefund>('POST', `/api/staff/refund-requests/${encodeURIComponent(reference)}/review`, { decision })

export const listUsers = () => getJson<AdminUser[]>('/api/admin/users')
export const changeRole = (id: number, role: 'support_agent' | 'admin') =>
  sendJson<AdminUser>('PATCH', `/api/admin/users/${id}/role`, { role })
export const setUserActive = (id: number, isActive: boolean) =>
  sendJson<AdminUser>('PATCH', `/api/admin/users/${id}/active`, { is_active: isActive })
export const listAudit = (outcome: string) =>
  getJson<AuditEvent[]>(`/api/admin/audit?limit=50${outcome ? `&outcome=${encodeURIComponent(outcome)}` : ''}`)