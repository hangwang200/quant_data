import { useEffect, useState } from 'react'
import { Button, ErrorBox, Loading } from './ui'
import { Chart, axisStyle } from './Chart'
import { api } from '../lib/api'
import { useColors } from '../lib/theme'
import { fmt } from '../lib/format'

interface Item { name: string; value: number }
interface Period {
  report_date: string
  fetched_at: string
  assets: Item[]
  liabilities: Item[]
  total_assets: number | null
  total_liabilities: number | null
  equity: number | null
  parent_equity: number | null
  debt_ratio: number | null
  current_ratio: number | null
}

const yi = (v: number | null | undefined) => (v == null ? '—' : fmt(v / 1e8, 2))
const periodLabel = (d: string) => {
  const [y, m] = d.split('-')
  return `${y} ${({ '03': '一季报', '06': '半年报', '09': '三季报', '12': '年报' } as Record<string, string>)[m] ?? d}`
}

/** 资产负债结构：资产科目（蓝）与负债科目（红）并列柱状图，柱顶标注金额（亿元） */
export function BalanceSheet({ code }: { code: string }) {
  const c = useColors()
  const [data, setData] = useState<Period[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [idx, setIdx] = useState(0)

  const load = (refresh = false) => {
    setBusy(true); setErr(null)
    api.get<Period[]>(`/api/stocks/${code}/balance${refresh ? '?refresh=true' : ''}`)
      .then(d => { setData(d); setIdx(0) })
      .catch(e => setErr((e as Error).message))
      .finally(() => setBusy(false))
  }
  useEffect(() => { setData(null); load() }, [code]) // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <ErrorBox error={err} />
  if (!data) return <Loading text="正在获取资产负债表…" />
  if (!data.length) return <div className="py-10 text-center text-faint">暂无资产负债表数据</div>

  const p = data[Math.min(idx, data.length - 1)]
  // 上年同期，用于提示框中的同比
  const ly = data.find(x => x.report_date === `${+p.report_date.slice(0, 4) - 1}${p.report_date.slice(4)}`)
  const prev = new Map<string, number>([...(ly?.assets ?? []), ...(ly?.liabilities ?? [])].map(i => [i.name, i.value]))
  const ASSET = c.series[0], LIAB = c.series[4]
  const names = [...p.assets.map(i => i.name), ...p.liabilities.map(i => i.name)]
  const nA = p.assets.length
  const val = (v: number) => +(v / 1e8).toFixed(2)
  const assetData = names.map((_, i) => (i < nA ? val(p.assets[i].value) : null))
  const liabData = names.map((_, i) => (i >= nA ? val(p.liabilities[i - nA].value) : null))
  const bar = (name: string, data: (number | null)[], color: string) => ({
    name, type: 'bar' as const, stack: 'bs', data, barMaxWidth: 26,
    itemStyle: { color, borderRadius: [4, 4, 0, 0] },
    label: { show: true, position: 'top' as const, color: c.muted, fontSize: 11, formatter: (o: any) => (o.value == null ? '' : fmt(o.value, 2)) },
    emphasis: { focus: 'none' as const },
  })

  const summary: [string, string][] = [
    ['总资产', `${yi(p.total_assets)} 亿`],
    ['总负债', `${yi(p.total_liabilities)} 亿`],
    ['所有者权益', `${yi(p.equity)} 亿`],
    ['资产负债率', p.debt_ratio == null ? '—' : `${fmt(p.debt_ratio, 1)}%`],
    ['流动比率', p.current_ratio == null ? '—' : fmt(p.current_ratio, 2)],
  ]

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-[13px]">
          {summary.map(([k, v]) => (
            <div key={k} className="flex items-baseline gap-1.5"><dt className="text-muted">{k}</dt><dd className="num font-semibold">{v}</dd></div>
          ))}
        </dl>
        <div className="flex items-center gap-2">
          <select className="field h-8 w-auto py-0" value={idx} onChange={e => setIdx(+e.target.value)}>
            {data.map((x, i) => <option key={x.report_date} value={i}>{periodLabel(x.report_date)}（{x.report_date}）</option>)}
          </select>
          <Button variant="ghost" className="h-8 px-2.5 text-[12px]" disabled={busy} onClick={() => load(true)} title={`缓存于 ${p.fetched_at}`}>
            {busy ? '刷新中…' : '刷新'}
          </Button>
        </div>
      </div>
      <Chart height={380} option={{
        legend: { data: ['资产', '负债'] },
        grid: { left: 8, right: 16, top: 40, bottom: 8, containLabel: true },
        tooltip: {
          trigger: 'item',
          formatter: (o: any) => {
            const v = o.value as number, raw = v * 1e8
            const share = p.total_assets ? (raw / p.total_assets) * 100 : null
            const last = prev.get(o.name)
            const yoy = last ? ((raw - last) / Math.abs(last)) * 100 : null
            return `<b>${o.name}</b>（${o.seriesName}）<br/>${fmt(v, 2)} 亿元`
              + (share == null ? '' : `<br/>占总资产 ${fmt(share, 1)}%`)
              + (yoy == null ? '' : `<br/>较上年同期 ${yoy >= 0 ? '+' : ''}${fmt(yoy, 1)}%`)
          },
        },
        xAxis: {
          type: 'category', data: names, ...axisStyle(c), splitLine: { show: false },
          axisLabel: { color: c.muted, fontSize: 11, rotate: 45, interval: 0 },
        },
        yAxis: { type: 'value', ...axisStyle(c), name: '亿元', nameTextStyle: { color: c.faint, fontSize: 11, align: 'right' } },
        series: [bar('资产', assetData, ASSET), bar('负债', liabData, LIAB)],
      }} />
      <div className="mt-1 text-[11px] text-faint">
        数据来源东方财富 F10 合并资产负债表；明细科目归并为结构项，未单列的科目计入"其他流动/非流动"项，各项合计等于报表合计。悬停查看占总资产比例与同比。
      </div>
    </div>
  )
}
