export type Role = 'customer' | 'support_agent' | 'admin'

export interface Profile {
  id: number
  email: string
  name: string
  role: Role
}

export interface StaffTicket {
  reference: string
  order_number: string | null
  category: string
  status: string
  subject: string
  description: string
  customer_name: string
  customer_email: string
  created_at: string
  updated_at: string
}

export interface StaffRefund {
  reference: string
  order_number: string
  reason: string
  status: string
  amount_cents: number
  requires_support_approval: boolean
  evidence_photo_count: number
  customer_note: string | null
  customer_name: string
  customer_email: string
  created_at: string
}

export interface AdminUser {
  id: number
  email: string
  full_name: string
  role: Role
  is_active: boolean
  customer_id: number | null
  created_at: string
  last_login_at: string | null
}

export interface AuditEvent {
  id: number
  created_at: string
  user_id: number | null
  role: string | null
  action: string
  resource_type: string | null
  resource_id: string | null
  outcome: string
  detail: string | null
  channel: string
  ip: string | null
  email_hash: string | null
}