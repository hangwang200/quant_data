export const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

export function fmt(v: unknown, digits = 2): string {
  return isNum(v) ? v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : '—'
}

/** 金额（元）→ 亿 / 万 */
export function money(v: unknown): string {
  if (!isNum(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1e12) return `${fmt(v / 1e12, 2)}万亿`
  if (a >= 1e8) return `${fmt(v / 1e8, 2)}亿`
  if (a >= 1e4) return `${fmt(v / 1e4, 1)}万`
  return fmt(v, 0)
}

/** 已经是百分数的值，如 12.3 → "12.30%" */
export function pct(v: unknown, digits = 2, sign = false): string {
  if (!isNum(v)) return '—'
  return `${sign && v > 0 ? '+' : ''}${fmt(v, digits)}%`
}

/** 小数比例，如 0.123 → "12.30%" */
export function ratio(v: unknown, digits = 2, sign = false): string {
  return isNum(v) ? pct(v * 100, digits, sign) : '—'
}

export function trendClass(v: unknown): string {
  if (!isNum(v) || v === 0) return 'text-muted'
  return v > 0 ? 'text-up' : 'text-down'
}

export function shortCode(code: string): string {
  return code?.split('.')[1] ?? code
}
