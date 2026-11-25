import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Button, Card, ErrorBox, Field, PageHeader, Segmented } from '../components/ui'
import { FormulaInput } from '../components/FactorSelect'
import { api, type Row } from '../lib/api'
import { useFetch } from '../lib/hooks'
import { useMeta } from '../lib/meta'
import { fmt, shortCode } from '../lib/format'

interface Preview {
  ok: boolean; error?: string; date?: string; n?: number; coverage?: number; is_bool?: boolean; true_count?: number | null
  mean?: number | null; quantiles?: number[]; top?: Row[]
}

const EXAMPLES: { name: string; label: string; expr: string; better: 'high' | 'low'; desc: string }[] = [
  { name: 'value_quality', label: '价值质量排名', expr: 'rank(ep) + rank(roe_ann)', better: 'high', desc: 'EP 与 ROE 截面排名等权相加' },
  { name: 'div_quality', label: '红利质量', expr: 'zscore(dividend_yield) + 0.5 * zscore(roe_ann) - 0.5 * zscore(vol_60)', better: 'high', desc: '高股息 + 高 ROE + 低波动' },
  { name: 'stable_div', label: '稳定分红', expr: '(dividend_yield > 3) and (30 <= payout_ratio <= 80) and (roe_ann > 8)', better: 'high', desc: '逻辑条件：结果为 1/0，适合作过滤' },
  { name: 'peg', label: 'PEG', expr: 'where((pe_ttm > 0) and (net_profit_yoy > 0), pe_ttm / net_profit_yoy, 1 / 0)', better: 'low', desc: '1 / 0 产生缺失值：不满足条件的股票被剔除' },
  { name: 'ind_value', label: '行业内估值', expr: 'ind_rank(ep) + ind_rank(bp)', better: 'high', desc: '行业内排名，消除行业估值差异' },
  { name: 'crowd_timing', label: '拥挤择时·价值', expr: 'where(mkt_amt_top5 < 40, rank(ep), 1 / 0)', better: 'high', desc: '成交过度集中时整体剔除（回测中表现为空仓）' },
  { name: 'quality_mom', label: '质量动量', expr: 'rank(roe_delta) * 0.5 + rank(mom_12_1) * 0.5', better: 'high', desc: 'ROE 改善 + 中期动量' },
]

const MKT_FIELDS: [string, string][] = [
  ['mkt_amt_top5', '近一周成交额前5%个股占比%'], ['mkt_sentiment', '情绪指数'], ['mkt_above_ma20', '站上20日线比例%'],
  ['mkt_breadth', '上涨占比%'], ['mkt_amount', '全市场成交额(亿)'],
]

const FUNCS: [string, string][] = [
  ['rank(x)', '截面百分位排名 0~1'], ['zscore(x)', '截面去极值标准化'], ['demean(x)', '截面去均值'],
  ['ind_rank(x)', '行业内排名'], ['ind_zscore(x)', '行业内标准化'], ['where(c, a, b)', '条件为真取 a 否则 b'],
  ['a if c else b', '同 where'], ['min(a, b) / max(a, b)', '逐元素最小/最大'], ['clip(x, lo, hi)', '截断'],
  ['fillna(x, v)', '缺失值填充'], ['isnull(x)', '是否缺失 → 1/0'], ['abs log sqrt sign exp', '数学函数'],
  ['and or not  & | ~', '逻辑运算 → 1/0'], ['> >= < <= == !=', '比较，可链式 10 < x < 30'],
]

export default function Formulas() {
  const nav = useNavigate()
  const { meta, reload } = useMeta()
  const list = useFetch<Row[]>('/api/formulas')
  const [name, setName] = useState('')
  const [label, setLabel] = useState('')
  const [expr, setExpr] = useState('rank(ep) + rank(roe_ann)')
  const [better, setBetter] = useState<'high' | 'low'>('high')
  const [prev, setPrev] = useState<Preview | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const timer = useRef<number | undefined>(undefined)

  // 输入停顿 500ms 后自动校验并试算
  useEffect(() => {
    window.clearTimeout(timer.current)
    if (!expr.trim()) { setPrev(null); return }
    timer.current = window.setTimeout(() => {
      api.post<Preview>('/api/formulas/validate', { expr, name: name || null }).then(setPrev).catch(e => setPrev({ ok: false, error: e.message }))
    }, 500)
    return () => window.clearTimeout(timer.current)
  }, [expr, name])

  const insert = (t: string) => setExpr(e => (e && !e.endsWith(' ') ? `${e} ${t}` : e + t))
  const save = async () => {
    setErr(null); setMsg(null)
    try {
      await api.post('/api/formulas', { name, label: label || name, expr, better })
      setMsg(`已保存「${label || name}」，可在选股器、回测、因子分析中使用`)
      list.reload(); reload()
    } catch (e) { setErr((e as Error).message) }
  }
  const edit = (r: Row) => { setName(r.name); setLabel(r.label); setExpr(r.expr); setBetter(r.better) }
  const remove = async (n: string) => {
    setErr(null)
    try { await api.del(`/api/formulas/${n}`); list.reload(); reload() } catch (e) { setErr((e as Error).message) }
  }

  const groups: Record<string, [string, string][]> = {}
  for (const [k, f] of Object.entries(meta?.factors ?? {})) {
    if (filter && !(k.includes(filter) || f.label.includes(filter))) continue
    ;(groups[f.group] ??= []).push([k, f.label])
  }

  return (
    <>
      <PageHeader eyebrow="Formula Factors" title="公式因子"
        desc="用四则运算、比较与逻辑、截面函数组合已有因子；保存后与内置因子一样用于选股、回测和因子分析（每个信号日按当时数据计算）" />
      <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
        <div className="space-y-4">
          <Card title="编辑公式">
            <div className="space-y-4">
              <FormulaInput value={expr} onChange={setExpr} rows={3} placeholder="例如：rank(ep) + rank(roe_ann)" />
              <div className="min-h-[22px] text-[12px]">
                {prev == null ? null : prev.ok
                  ? <span className="text-down">✓ 公式有效 · {prev.date} 截面覆盖 {prev.coverage}/{prev.n} 只
                      {prev.is_bool ? ` · 为真 ${prev.true_count} 只（逻辑公式）` : ` · 均值 ${fmt(prev.mean, 3)}`}</span>
                  : <span className="text-up">✗ {prev.error}</span>}
              </div>
              <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto]">
                <Field label="标识名（英文小写，用于在其他公式中引用）"><input className="field font-mono" value={name} placeholder="my_factor" onChange={e => setName(e.target.value.toLowerCase())} /></Field>
                <Field label="显示名称"><input className="field" value={label} placeholder="我的因子" onChange={e => setLabel(e.target.value)} /></Field>
                <div className="flex flex-col gap-1.5">
                  <span className="text-[12px] font-medium text-muted">方向</span>
                  <Segmented value={better} onChange={setBetter} options={[{ value: 'high', label: '越大越好' }, { value: 'low', label: '越小越好' }]} />
                </div>
              </div>
              <div className="flex items-center gap-3">
                <Button onClick={save} disabled={!name || !prev?.ok}>保存公式因子</Button>
                {name && meta?.factors[name]?.group === '自定义' && <span className="text-[12px] text-faint">将覆盖同名公式</span>}
                {msg && <span className="text-[12px] text-down">{msg}</span>}
              </div>
              {err && <ErrorBox error={err} />}
            </div>
          </Card>

          {prev?.ok && prev.top && (
            <Card title={`最新截面试算 · 前 10 名`} extra={prev.quantiles?.length ? <span className="num text-[12px] text-faint">
              分位 5/25/50/75/95%：{prev.quantiles.map(q => fmt(q, 2)).join(' / ')}</span> : null}>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
                {prev.top.map(r => (
                  <button key={r.code} onClick={() => nav(`/stock/${r.code}`)} className="cursor-pointer rounded-lg border border-line px-3 py-2 text-left hover:border-accent">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-[13px] font-medium">{r.name}</span>
                      <span className="num shrink-0 text-[12px] font-semibold text-accent-text">{fmt(r.value, 3)}</span>
                    </div>
                    <div className="truncate text-[11px] text-faint" title={r.industry}>{shortCode(r.code)} · {r.industry ?? '—'}</div>
                  </button>
                ))}
              </div>
            </Card>
          )}

          <Card title="已保存的公式因子">
            {list.data?.length ? (
              <ul className="divide-y divide-line">
                {list.data.map(r => (
                  <li key={r.name} className="flex flex-wrap items-center justify-between gap-3 py-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 text-[13px] font-medium">{r.label}
                        <span className="font-mono text-[11px] text-faint">{r.name}</span>
                        <Badge tone={r.better === 'high' ? 'up' : 'down'}>{r.better === 'high' ? '越大越好' : '越小越好'}</Badge>
                      </div>
                      <code className="mt-1 block truncate font-mono text-[12px] text-muted">{r.expr}</code>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button variant="ghost" onClick={() => edit(r)}>编辑</Button>
                      <Button variant="ghost" onClick={() => nav(`/analysis?tab=single&factor=${r.name}`)}>分析</Button>
                      <Button variant="danger" onClick={() => remove(r.name)}>删除</Button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : <div className="text-[13px] text-faint">暂无。可以从右侧的示例开始。</div>}
          </Card>
        </div>

        <div className="space-y-4">
          <Card title="示例">
            <div className="space-y-2">
              {EXAMPLES.map(e => (
                <button key={e.name} onClick={() => { setName(e.name); setLabel(e.label); setExpr(e.expr); setBetter(e.better) }}
                  className="block w-full cursor-pointer rounded-lg border border-line px-3 py-2 text-left transition hover:border-accent hover:bg-accent-soft">
                  <div className="text-[13px] font-medium">{e.label}</div>
                  <code className="block truncate font-mono text-[11px] text-muted">{e.expr}</code>
                  <div className="text-[11px] text-faint">{e.desc}</div>
                </button>
              ))}
            </div>
          </Card>
          <Card title="可用因子（点击插入）">
            <input className="field mb-3 w-full" placeholder="搜索因子…" value={filter} onChange={e => setFilter(e.target.value)} />
            <div className="max-h-[360px] space-y-3 overflow-auto pr-1">
              {Object.entries(groups).map(([g, items]) => (
                <div key={g}>
                  <div className="eyebrow mb-1.5">{g}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {items.map(([k, l]) => (
                      <button key={k} title={l} onClick={() => insert(k)} className="cursor-pointer rounded-md bg-surface-2 px-2 py-1 font-mono text-[11.5px] text-muted hover:bg-accent-soft hover:text-accent-text">
                        {k}<span className="ml-1 font-sans text-faint">{l}</span>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
              <div>
                <div className="eyebrow mb-1.5">行情字段</div>
                <div className="flex flex-wrap gap-1.5">
                  {['close', 'pct_chg', 'amount', 'listed_days', 'is_st'].map(k => (
                    <button key={k} onClick={() => insert(k)} className="cursor-pointer rounded-md bg-surface-2 px-2 py-1 font-mono text-[11.5px] text-muted hover:bg-accent-soft">{k}</button>
                  ))}
                </div>
                <div className="eyebrow mb-1.5 mt-3">市场字段（择时）</div>
                <div className="flex flex-wrap gap-1.5">
                  {MKT_FIELDS.map(([k, l]) => (
                    <button key={k} title={l} onClick={() => insert(k)} className="cursor-pointer rounded-md bg-surface-2 px-2 py-1 font-mono text-[11.5px] text-muted hover:bg-accent-soft hover:text-accent-text">
                      {k}<span className="ml-1 font-sans text-faint">{l}</span>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </Card>
          <Card title="函数与运算符">
            <dl className="space-y-1.5 text-[12px]">
              {FUNCS.map(([f, d]) => (
                <div key={f} className="flex justify-between gap-3"><dt className="font-mono text-text">{f}</dt><dd className="text-right text-faint">{d}</dd></div>
              ))}
            </dl>
            <p className="mt-3 text-[11px] leading-relaxed text-faint">逻辑结果为 1（真）/ 0（假）。单位与因子一致：估值为倍数，比率类为 %，成交额/市值为亿元。任一输入缺失时结果为缺失，回测中该股票当期不参与打分。</p>
          </Card>
        </div>
      </div>
    </>
  )
}
