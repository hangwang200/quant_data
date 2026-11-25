import { useEffect, useMemo, useState } from 'react'
import { Card, Empty, ErrorBox, Loading, PageHeader, Segmented } from '../components/ui'
import { Chart, axisStyle } from '../components/Chart'
import { StockSearch } from '../components/StockSearch'
import { useFetch } from '../lib/hooks'
import { useColors } from '../lib/theme'
import { fmt, pct, shortCode } from '../lib/format'
import type { Row } from '../lib/api'

interface CompareRes { series: { code: string; name: string; dates: string[]; values: number[] }[]; table: Row[] }

// 雷达维度：在全股票池中的分位（越高越好；低估值、低波动取反）
const RADAR: { key: string; label: string; invert?: boolean }[] = [
  { key: 'roe_ann', label: '盈利能力 ROE' },
  { key: 'gross_margin', label: '毛利率' },
  { key: 'revenue_yoy', label: '成长 营收同比' },
  { key: 'pe_ttm', label: '估值 低PE', invert: true },
  { key: 'mom_60', label: '动量 60日' },
  { key: 'vol_60', label: '稳定 低波动', invert: true },
]

function loadSaved(): Row[] {
  try { return JSON.parse(localStorage.getItem('compare') ?? '') } catch { return [] }
}

export default function Compare() {
  const c = useColors()
  const [picked, setPicked] = useState<Row[]>(() => {
    const s = loadSaved()
    return s.length ? s : [{ code: 'sh.600519', name: '贵州茅台' }, { code: 'sz.000858', name: '五粮液' }, { code: 'sh.600809', name: '山西汾酒' }]
  })
  const [years, setYears] = useState(3)
  useEffect(() => { try { localStorage.setItem('compare', JSON.stringify(picked)) } catch { /* ignore */ } }, [picked])

  const codes = picked.map(p => p.code).join(',')
  const { data, error, loading } = useFetch<CompareRes>(codes ? `/api/compare?codes=${codes}&years=${years}` : null)
  const universe = useFetch<{ rows: Row[] }>('/api/market/stocks')

  const radar = useMemo(() => {
    if (!data || !universe.data) return null
    const all = universe.data.rows
    const rank = (key: string, v: number | null, invert?: boolean) => {
      if (v == null) return 0
      const vals = all.map(r => r[key]).filter((x: unknown): x is number => typeof x === 'number')
      const p = vals.filter(x => x < v).length / Math.max(vals.length, 1) * 100
      return Math.round(invert ? 100 - p : p)
    }
    return data.table.map(r => ({ name: r.name, value: RADAR.map(d => rank(d.key, r[d.key], d.invert)) }))
  }, [data, universe.data])

  const add = (r: Row) => setPicked(p => (p.some(x => x.code === r.code) || p.length >= 6 ? p : [...p, r]))

  return (
    <>
      <PageHeader eyebrow="Compare" title="公司对比" desc="最多选择 6 家公司，对比走势、财务与因子画像"
        right={<StockSearch onSelect={add} placeholder="添加公司…" />} />
      <div className="mb-4 flex flex-wrap gap-2">
        {picked.map((p, i) => (
          <span key={p.code} className="card inline-flex items-center gap-2 px-3 py-1.5 text-[13px]">
            <span className="h-2 w-2 rounded-full" style={{ background: c.series[i % c.series.length] }} />
            {p.name}<span className="num text-faint">{shortCode(p.code)}</span>
            <button className="cursor-pointer text-faint hover:text-up" onClick={() => setPicked(x => x.filter(y => y.code !== p.code))}>×</button>
          </span>
        ))}
      </div>
      {error && <ErrorBox error={error} />}
      {!picked.length ? <Card><Empty text="请先添加公司" /></Card> : !data ? <Loading /> : (
        <>
          <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
            <Card title="累计收益（后复权，期初 = 1）" extra={<Segmented value={years} onChange={setYears} options={[1, 3, 5, 10].map(y => ({ value: y, label: `${y}年` }))} />}>
              {loading ? <Loading /> : (
                <Chart height={340} option={{
                  xAxis: { type: 'category', data: data.series[0]?.dates, ...axisStyle(c), splitLine: { show: false } },
                  yAxis: { type: 'value', scale: true, ...axisStyle(c) },
                  dataZoom: [{ type: 'inside' }],
                  series: data.series.map(s => ({ name: s.name, type: 'line', showSymbol: false, data: s.values, lineStyle: { width: 1.6 } })),
                }} />
              )}
            </Card>
            <Card title="因子画像（股票池分位）">
              {radar ? (
                <Chart height={340} option={{
                  tooltip: { trigger: 'item' },
                  legend: { bottom: 0, top: 'auto', right: 'center' },
                  radar: {
                    indicator: RADAR.map(d => ({ name: d.label, max: 100 })), radius: '62%', center: ['50%', '48%'],
                    axisName: { color: c.muted, fontSize: 11 }, splitLine: { lineStyle: { color: c.line } },
                    splitArea: { show: false }, axisLine: { lineStyle: { color: c.line } },
                  },
                  series: [{ type: 'radar', symbolSize: 4, areaStyle: { opacity: 0.08 }, data: radar }],
                }} />
              ) : <Loading />}
            </Card>
          </div>
          <Card className="mt-4" title="关键指标">
            <div className="overflow-x-auto">
              <table className="w-full text-[13px]">
                <thead><tr className="border-b border-line text-left text-[12px] text-muted">
                  <th className="px-3 py-2.5 font-medium">指标</th>
                  {data.table.map(r => <th key={r.code} className="px-3 py-2.5 text-right font-medium">{r.name}</th>)}
                </tr></thead>
                <tbody>
                  {([
                    ['行业', (r: Row) => r.industry ?? '—'],
                    ['最新价', (r: Row) => fmt(r.close)],
                    [`${years}年年化收益`, (r: Row) => pct(r.ann_return, 1, true)],
                    ['年化波动率', (r: Row) => pct(r.ann_vol, 1)],
                    ['最大回撤', (r: Row) => pct(r.max_dd, 1)],
                    ['PE(TTM)', (r: Row) => fmt(r.pe_ttm, 1)],
                    ['PB', (r: Row) => fmt(r.pb)],
                    ['ROE(年化)', (r: Row) => pct(r.roe_ann, 1)],
                    ['毛利率', (r: Row) => pct(r.gross_margin, 1)],
                    ['营收同比', (r: Row) => pct(r.revenue_yoy, 1, true)],
                    ['净利润同比', (r: Row) => pct(r.net_profit_yoy, 1, true)],
                    ['流通市值(亿)', (r: Row) => fmt(r.float_mv, 0)],
                    ['财报期', (r: Row) => r.fin_report_date ?? '—'],
                  ] as [string, (r: Row) => string][]).map(([label, f]) => (
                    <tr key={label} className="border-b border-line/70">
                      <td className="px-3 py-2.5 text-muted">{label}</td>
                      {data.table.map(r => <td key={r.code} className="num px-3 py-2.5 text-right">{f(r)}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </>
  )
}
