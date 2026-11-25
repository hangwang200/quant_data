import type { SelectHTMLAttributes } from 'react'
import { useMeta } from '../lib/meta'
import { cx } from './ui'

/** 因子下拉框：按分组（估值 / 质量 / 分红 / … / 自定义）显示 */
export function FactorSelect({ value, onChange, className, ...rest }: Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange'> & {
  value: string; onChange: (v: string) => void
}) {
  const { meta } = useMeta()
  const groups: Record<string, [string, string][]> = {}
  for (const [k, f] of Object.entries(meta?.factors ?? {})) (groups[f.group] ??= []).push([k, f.label])
  return (
    <select {...rest} className={cx('field min-w-0', className)} value={value} onChange={e => onChange(e.target.value)}>
      {Object.entries(groups).map(([g, items]) => (
        <optgroup key={g} label={g}>
          {items.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </optgroup>
      ))}
    </select>
  )
}

/** 股票池（历史成分）+ 中性化选择 */
export function UniverseSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { meta } = useMeta()
  return (
    <select className="field" value={value} onChange={e => onChange(e.target.value)}>
      {Object.entries(meta?.universes ?? { all: '全 A 股' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
    </select>
  )
}

export function NeutralToggle({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const { meta } = useMeta()
  return (
    <div className="flex gap-1.5">
      {Object.entries(meta?.neutralize ?? {}).map(([k, label]) => {
        const on = value.includes(k)
        return (
          <button key={k} type="button" onClick={() => onChange(on ? value.filter(x => x !== k) : [...value, k])}
            className={cx('h-[30px] cursor-pointer rounded-md border px-2.5 text-[12px] transition',
              on ? 'border-accent bg-accent-soft font-medium text-accent-text' : 'border-line text-muted hover:text-text')}>
            {on ? '✓ ' : ''}{label}中性
          </button>
        )
      })}
    </div>
  )
}

/** 公式输入框（等宽字体） */
export function FormulaInput({ value, onChange, placeholder, rows = 2 }: {
  value: string; onChange: (v: string) => void; placeholder?: string; rows?: number
}) {
  return (
    <textarea className="field num min-h-0 w-full resize-y py-2 font-mono text-[12.5px] leading-relaxed" rows={rows} spellCheck={false}
      value={value} placeholder={placeholder} onChange={e => onChange(e.target.value)} />
  )
}
