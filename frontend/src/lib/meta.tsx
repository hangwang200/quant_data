import { createContext, useContext, type ReactNode } from 'react'
import type { Meta } from './api'
import { useFetch } from './hooks'

const Ctx = createContext<{ meta: Meta | null; error: string | null; reload: () => void }>({ meta: null, error: null, reload: () => {} })

export function MetaProvider({ children }: { children: ReactNode }) {
  const { data, error, reload } = useFetch<Meta>('/api/meta')
  return <Ctx.Provider value={{ meta: data, error, reload }}>{children}</Ctx.Provider>
}

export const useMeta = () => useContext(Ctx)

export function factorLabel(meta: Meta | null, key: string) {
  return meta?.factors[key]?.label ?? key
}
