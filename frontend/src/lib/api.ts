export type Row = Record<string, any>

export interface FactorMeta { label: string; group: string; unit: string; better: 'high' | 'low'; expr?: string }

export interface Meta {
  ready: boolean
  start?: string
  end?: string
  n_stocks?: number
  industries?: string[]
  factors: Record<string, FactorMeta>
  benchmarks: Record<string, string>
  universes: Record<string, string>
  neutralize: Record<string, string>
  etl: Row[]
}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try { const j = await res.json(); msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* ignore */ }
    throw new Error(msg)
  }
  return res.json()
}

export const api = {
  get: <T,>(url: string) => req<T>('GET', url),
  post: <T,>(url: string, body: unknown) => req<T>('POST', url, body),
  del: <T,>(url: string) => req<T>('DELETE', url),
  patch: <T,>(url: string, body: unknown) => req<T>('PATCH', url, body),
}
