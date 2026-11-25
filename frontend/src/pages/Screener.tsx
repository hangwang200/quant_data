import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Button, Card, ErrorBox, Field, Loading, PageHeader } from '../components/ui'
import { DataTable, type Col } from '../components/DataTable'
import { FactorSelect, FormulaInput } from '../components/FactorSelect'
import { api, type Row } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { factorLabel, useMeta } from '../lib/meta'
import { fmt, pct, shortCode, trendClass } from '../lib/format'

export interface Rule { field: string; min: number | null; max: number | null }
export interface Pool { pool_id: string; name: string; rules: { rules: Rule[]; industries: string[]; exclude_st: boolean; expr?: string | null }; created_at: string }

const PRESETS: { name: string; desc: string; rules: Rule[] }[] = [
  { name: '低估值高盈利', desc: 'PE<20 · ROE>12%', rules: [{ field: 'pe_ttm', min: 0, max: 20 }, { field: 'roe_ann', min: 12, max: null }] },
  { name: '高质量', desc: 'ROE>15% · 毛利率>30%', rules: [{ field: 'roe_ann', min: 15, max: null }, { field: 'gross_margin', min: 30, max: null }] },
  { name: '低波稳健', desc: '60日波动率<25% · PB<3', rules: [{ field: 'vol_60', min: null, max: 25 }, { field: 'pb', min: 0, max: 3 }] },
  { name: '成长动量', desc: '营收同比>20% · 60日动量>0', rules: [{ field: 'revenue_yoy', min: 20, max: null }, { field: 'mom_60', min: 0, max: null }] },
  { name: '高股息', desc: '股息率>4% · 分红率 30–80%', rules: [{ field: 'dividend_yield', min: 4, max: null }, { field: 'payout_ratio', min: 30, max: 80 }] },
  { name: '现金牛', desc: 'ROE>12% · 现金流/EPS>1', rules: [{ field: 'roe_ann', min: 12, max: null }, { field: 'ocf_to_eps', min: 1, max: null }] },
]

const numOrNull = (s: string) => (s.trim() === '' || Number.isNaN(+s) ? null : +s)

export default function Screener() {
  const nav = useNavigate()
  const { meta } = useMeta()
  const [rules, setRules] = useState<Rule[]>(PRESETS[0].rules)
  const [inds, setInds] = useState<string[]>([])
  const [expr, setExpr] = useState('')
  const [res, setRes] = useState<{ date: string; count: number; rows: Row[] } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [poolName, setPoolName] = useState('')
  const pools = useFetch<Pool[]>('/api/pools')

  const run = async (r = rules, i = inds, x = expr) => {
    setBusy(true); setErr(null)
    try { setRes(await api.post('/api/screener', { rules: r, industries: i, sort: 'roe_ann', expr: x.trim() || null })) }
    catch (e) { setErr((e as Error).message) }
    finally { setBusy(false) }
  }
  useEffect(() => { if (meta?.ready) run() }, [meta?.ready]) // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!poolName.trim()) return
    await api.post('/api/pools', { name: poolName.trim(), rules, industries: inds, exclude_st: true, expr: expr.trim() || null })
    setPoolName(''); pools.reload()
  }

  // 结果表展示：常用列 + 条件中用到的因子 + 公式里引用到的因子（含公式因子）
  const inExpr = Object.keys(meta?.factors ?? {}).filter(k => new RegExp(`\\b${k}\\b`).test(expr))
  const used = Array.from(new Set(['pe_ttm', 'pb', 'roe_ann', 'dividend_yield', 'vol_60', ...rules.map(r => r.field), ...inExpr]))
  const cols: Col[] = [
    { key: 'name', label: '股票', render: r => <div><div className="font-medium">{r.name}</div><div className="text-[11px] text-faint">{shortCode(r.code)}</div></div> },
    { key: 'industry', label: '行业', render: r => <span className="text-muted">{r.industry ?? '—'}</span> },
    { key: 'close', label: '收盘价', align: 'right', render: r => fmt(r.close) },
    { key: 'pct_chg', label: '涨跌幅', align: 'right', render: r => <span className={trendClass(r.pct_chg)}>{pct(r.pct_chg, 2, true)}</span> },
    ...used.map(k => ({
      key: k, label: factorLabel(meta, k), align: 'right' as const,
      render: (r: Row) => (meta?.factors[k]?.unit === '%' ? pct(r[k], 1) : fmt(r[k], k === 'pe_ttm' ? 1 : 2)),
    })),
  ]

  return (
    <>
      <PageHeader eyebrow="Screener" title="选股器" desc="组合 ROE、PE、股息率、波动率、行业与自定义公式构建股票池（全 A 股）；保存后可直接用于回测（每期按当时数据动态筛选）" />
      <div className="grid gap-4 xl:grid-cols-[380px_1fr]">
        <div className="space-y-4">
          <Card title="快速模板">
            <div className="grid grid-cols-2 gap-2">
              {PRESETS.map(p => (
                <button key={p.name} onClick={() => { setRules(p.rules); run(p.rules) }}
                  className="cursor-pointer rounded-lg border border-line px-3 py-2 text-left transition hover:border-accent hover:bg-accent-soft">
                  <div className="text-[13px] font-medium">{p.name}</div><div className="text-[11px] text-faint">{p.desc}</div>
                </button>
              ))}
            </div>
          </Card>
          <Card title="筛选条件" extra={<Button variant="ghost" onClick={() => setRules(r => [...r, { field: 'roe_ann', min: null, max: null }])}>+ 条件</Button>}>
            <div className="space-y-2.5">
              {rules.map((r, i) => (
                <div key={i} className="grid grid-cols-[1fr_72px_72px_24px] items-center gap-1.5">
                  <FactorSelect value={r.field} onChange={v => setRules(rs => rs.map((x, j) => (j === i ? { ...x, field: v } : x)))} />
                  <input className="field num min-w-0" placeholder="最小" defaultValue={r.min ?? ''} key={`${i}-${r.field}-min-${r.min}`}
                    onBlur={e => setRules(rs => rs.map((x, j) => (j === i ? { ...x, min: numOrNull(e.target.value) } : x)))} />
                  <input className="field num min-w-0" placeholder="最大" defaultValue={r.max ?? ''} key={`${i}-${r.field}-max-${r.max}`}
                    onBlur={e => setRules(rs => rs.map((x, j) => (j === i ? { ...x, max: numOrNull(e.target.value) } : x)))} />
                  <button className="cursor-pointer text-faint hover:text-up" onClick={() => setRules(rs => rs.filter((_, j) => j !== i))}>×</button>
                </div>
              ))}
              {!rules.length && <div className="text-[13px] text-faint">无条件：返回全部股票</div>}
              <p className="text-[11px] text-faint">单位：PE/PB 为倍数，其余为 %，成交额/市值为亿元</p>
            </div>
            <Field label="过滤公式（可选，与上面的条件同时满足）" className="mt-4">
              <FormulaInput value={expr} onChange={setExpr} placeholder="例如：(roe_ann > 15) and (dividend_yield > 3)，或 rank(ep) > 0.8" />
            </Field>
            <Field label="行业（可多选，不选为全部）" className="mt-4">
              <select className="field" value="" onChange={e => e.target.value && setInds(x => (x.includes(e.target.value) ? x : [...x, e.target.value]))}>
                <option value="">添加行业…</option>
                {meta?.industries?.map(i => <option key={i}>{i}</option>)}
              </select>
            </Field>
            {inds.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {inds.map(i => <button key={i} onClick={() => setInds(x => x.filter(y => y !== i))} className="cursor-pointer"><Badge tone="accent">{i} ×</Badge></button>)}
              </div>
            )}
            <Button className="mt-4 w-full" onClick={() => run()} disabled={busy}>{busy ? '筛选中…' : '开始筛选'}</Button>
          </Card>
          <Card title="已保存的股票池">
            <div className="mb-3 flex gap-2">
              <input className="field min-w-0 flex-1" placeholder="为当前条件命名…" value={poolName} onChange={e => setPoolName(e.target.value)} />
              <Button variant="ghost" onClick={save} disabled={!poolName.trim()}>保存</Button>
            </div>
            {pools.data?.length ? (
              <ul className="divide-y divide-line">
                {pools.data.map(p => (
                  <li key={p.pool_id} className="flex items-center justify-between gap-2 py-2.5">
                    <button className="min-w-0 cursor-pointer text-left" onClick={() => { setRules(p.rules.rules); setInds(p.rules.industries); setExpr(p.rules.expr ?? ''); run(p.rules.rules, p.rules.industries, p.rules.expr ?? '') }}>
                      <div className="truncate text-[13px] font-medium">{p.name}</div>
                      <div className="truncate text-[11px] text-faint">
                        {p.rules.rules.map(r => `${factorLabel(meta, r.field)}${r.min != null ? `≥${r.min}` : ''}${r.max != null ? `≤${r.max}` : ''}`).join(' · ') || '无条件'}
                        {p.rules.industries.length ? ` · ${p.rules.industries.join('/')}` : ''}
                        {p.rules.expr ? ` · ƒ ${p.rules.expr}` : ''}
                      </div>
                    </button>
                    <div className="flex shrink-0 gap-1">
                      <Button variant="ghost" onClick={() => nav(`/backtest?pool=${p.pool_id}`)}>回测</Button>
                      <Button variant="danger" onClick={async () => { await api.del(`/api/pools/${p.pool_id}`); pools.reload() }}>删除</Button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : <div className="text-[13px] text-faint">暂无</div>}
          </Card>
        </div>
        <Card title={res ? `筛选结果 · ${res.count} 只` : '筛选结果'} extra={res && <span className="text-[12px] text-faint">截面日期 {res.date}</span>}>
          {err && <ErrorBox error={err} />}
          {!res ? <Loading /> : <DataTable cols={cols} rows={res.rows} maxHeight={760} onRowClick={r => nav(`/stock/${r.code}`)} />}
        </Card>
      </div>
    </>
  )
}
