/** 迷你折线（表格内的累计 IC 走势），零线虚线 */
export function Spark({ values, width = 96, height = 24 }: { values: (number | null)[]; width?: number; height?: number }) {
  const v = values.map(x => x ?? 0)
  if (v.length < 2) return null
  const min = Math.min(0, ...v), max = Math.max(0, ...v)
  const span = max - min || 1
  const x = (i: number) => (i / (v.length - 1)) * width
  const y = (val: number) => height - 2 - ((val - min) / span) * (height - 4)
  const d = v.map((val, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(val).toFixed(1)}`).join('')
  const last = v[v.length - 1]
  return (
    <svg width={width} height={height} className="inline-block align-middle">
      <line x1={0} x2={width} y1={y(0)} y2={y(0)} stroke="var(--line-strong)" strokeDasharray="2 2" />
      <path d={d} fill="none" stroke={last >= 0 ? 'var(--up)' : 'var(--down)'} strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  )
}
