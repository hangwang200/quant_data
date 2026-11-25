/** 市场情绪仪表盘（半圆 5 段 + 指针） */
const SEGMENTS = [
  { from: 0, to: 25, label: '极度恐惧' },
  { from: 25, to: 45, label: '恐惧' },
  { from: 45, to: 55, label: '中性' },
  { from: 55, to: 75, label: '贪婪' },
  { from: 75, to: 100, label: '极度贪婪' },
]

export function sentimentLabel(v: number) {
  return SEGMENTS.find(s => v >= s.from && v <= s.to)?.label ?? '中性'
}

export function sentimentTone(v: number): 'down' | 'warn' | 'neutral' | 'up' {
  if (v < 25) return 'down'
  if (v < 45) return 'warn'
  if (v <= 55) return 'neutral'
  return 'up'
}

const CX = 160, CY = 160, R0 = 82, R1 = 140

function polar(v: number, r: number) {
  const a = Math.PI * (1 - v / 100)
  return [CX + r * Math.cos(a), CY - r * Math.sin(a)]
}

function arc(from: number, to: number) {
  const gap = 0.6
  const [x1, y1] = polar(from + gap, R1), [x2, y2] = polar(to - gap, R1)
  const [x3, y3] = polar(to - gap, R0), [x4, y4] = polar(from + gap, R0)
  return `M${x1},${y1} A${R1},${R1} 0 0 1 ${x2},${y2} L${x3},${y3} A${R0},${R0} 0 0 0 ${x4},${y4} Z`
}

export function Gauge({ value }: { value: number }) {
  const active = SEGMENTS.findIndex(s => value >= s.from && value <= s.to)
  const [nx, ny] = polar(value, R1 - 18)
  const tone = sentimentTone(value)
  const fill = { down: 'var(--down-soft)', warn: 'var(--warn-soft)', neutral: 'var(--surface-2)', up: 'var(--up-soft)' }[tone]
  const stroke = { down: 'var(--down)', warn: 'var(--warn)', neutral: 'var(--line-strong)', up: 'var(--up)' }[tone]
  return (
    <svg viewBox="0 0 320 190" className="w-full max-w-[420px]" role="img" aria-label={`情绪指数 ${value.toFixed(0)}`}>
      {SEGMENTS.map((s, i) => {
        const [lx, ly] = polar((s.from + s.to) / 2, (R0 + R1) / 2)
        const on = i === active
        return (
          <g key={s.label}>
            <path d={arc(s.from, s.to)} fill={on ? fill : 'var(--surface-2)'} stroke={on ? stroke : 'none'} strokeWidth={1.5} />
            <text x={lx} y={ly} textAnchor="middle" dominantBaseline="middle" fontSize={s.to - s.from < 15 ? 10 : 11}
              fontWeight={600} fill={on ? 'var(--text)' : 'var(--faint)'}>{s.label}</text>
          </g>
        )
      })}
      {[0, 25, 50, 75, 100].map(t => {
        const [x, y] = polar(t, R0 - 12)
        return <text key={t} x={x} y={y} textAnchor="middle" dominantBaseline="middle" fontSize={10} fill="var(--faint)">{t}</text>
      })}
      <line x1={CX} y1={CY} x2={nx} y2={ny} stroke="var(--text)" strokeWidth={4} strokeLinecap="round" />
      <circle cx={CX} cy={CY} r={34} fill="var(--surface)" stroke="var(--line)" />
      <text x={CX} y={CY + 2} textAnchor="middle" dominantBaseline="middle" fontSize={28} fontWeight={700} fill="var(--text)"
        className="num">{value.toFixed(0)}</text>
    </svg>
  )
}
