import type { ButtonHTMLAttributes, ReactNode } from 'react'

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(' ')
}

export function PageHeader({ eyebrow, title, desc, right }: { eyebrow: string; title: string; desc?: string; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="eyebrow mb-2">{eyebrow}</div>
        <h1 className="text-[28px] font-bold tracking-tight leading-tight">{title}</h1>
        {desc && <p className="mt-1.5 text-muted">{desc}</p>}
      </div>
      {right && <div className="flex items-center gap-2">{right}</div>}
    </div>
  )
}

export function Card({ title, extra, children, className, pad = true }: {
  title?: ReactNode; extra?: ReactNode; children: ReactNode; className?: string; pad?: boolean
}) {
  return (
    <section className={cx('card', className)}>
      {(title || extra) && (
        <header className="flex items-center justify-between gap-3 px-5 pt-4 pb-1">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          {extra}
        </header>
      )}
      <div className={pad ? 'p-5 pt-3' : ''}>{children}</div>
    </section>
  )
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'up' | 'down' | 'muted' }) {
  return (
    <div className="card px-5 py-4">
      <div className="text-[12px] text-muted">{label}</div>
      <div className={cx('num mt-1.5 text-[26px] font-semibold tracking-tight',
        tone === 'up' && 'text-up', tone === 'down' && 'text-down', tone === 'muted' && 'text-muted')}>{value}</div>
      {sub && <div className="mt-1 text-[12px] text-faint">{sub}</div>}
    </div>
  )
}

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'accent' | 'up' | 'down' | 'warn' }) {
  const t = {
    neutral: 'bg-surface-2 text-muted',
    accent: 'bg-accent-soft text-accent-text',
    up: 'bg-up-soft text-up',
    down: 'bg-down-soft text-down',
    warn: 'bg-warn-soft text-warn',
  }[tone]
  return <span className={cx('inline-flex items-center rounded-md px-2 py-0.5 text-[12px] font-medium', t)}>{children}</span>
}

export function Button({ variant = 'primary', className, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: 'primary' | 'ghost' | 'danger' }) {
  const v = {
    primary: 'bg-accent text-white hover:opacity-90 disabled:opacity-50 dark:text-[#0e1014]',
    ghost: 'border border-line-strong bg-surface hover:bg-surface-2 disabled:opacity-50',
    danger: 'text-up hover:bg-up-soft',
  }[variant]
  return <button {...p} className={cx('inline-flex h-[34px] cursor-pointer items-center justify-center gap-1.5 rounded-lg px-3.5 text-[13px] font-medium transition disabled:cursor-not-allowed', v, className)} />
}

export function Segmented<T extends string | number>({ value, options, onChange }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void
}) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5">
      {options.map(o => (
        <button key={String(o.value)} onClick={() => onChange(o.value)}
          className={cx('h-7 cursor-pointer rounded-md px-2.5 text-[12px] font-medium transition',
            o.value === value ? 'bg-surface text-text shadow-sm' : 'text-muted hover:text-text')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Loading({ text = '加载中…' }: { text?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-16 text-muted">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-line-strong border-t-accent" />{text}
    </div>
  )
}

export function ErrorBox({ error }: { error: string }) {
  return <div className="rounded-xl border border-up/30 bg-up-soft px-4 py-3 text-[13px] text-up">{error}</div>
}

export function Empty({ text }: { text: string }) {
  return <div className="py-14 text-center text-faint">{text}</div>
}

export function Field({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cx('flex flex-col gap-1.5', className)}>
      <span className="text-[12px] font-medium text-muted">{label}</span>
      {children}
    </label>
  )
}
