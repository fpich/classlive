// Composants d'interaction pour chaque type de slide exercice.
import React, { useState, useMemo } from 'react'
import { SLIDE_TYPE_LABELS, type SlideType } from '@/types/api'

// ── Parsers du contenu Markdown ───────────────────────────────────────────

// Extrait les éléments d'une liste à puces (`- item` ou `1. item`)
export function parseListItems(content: string): string[] {
  return content.split('\n')
    .map((l) => l.replace(/^\s*(?:[-*+]\s+|\d+\.\s+)/, '').trim())
    .filter((l) => l.length > 0 && !l.startsWith('#'))
}

// Extrait les catégories : lignes en gras seules (**Nom**)
export function parseCategories(content: string): string[] {
  const cats: string[] = []
  for (const line of content.split('\n')) {
    const m = line.match(/^\s*\*\*([^*]+)\*\*\s*:?\s*$/)
    if (m) cats.push(m[1].trim())
  }
  return cats
}

// Extrait les paires pour association : `- gauche => droite`
export function parsePairs(content: string): { left: string; right: string }[] {
  const pairs: { left: string; right: string }[] = []
  for (const line of content.split('\n')) {
    const m = line.match(/^\s*-\s*(.+?)\s*=>\s*(.+?)\s*$/)
    if (m) pairs.push({ left: m[1].trim(), right: m[2].trim() })
  }
  return pairs
}

// Extrait la première image du markdown : ![alt](url)
export function parseFirstImage(content: string): string | null {
  const m = content.match(/!\[[^\]]*\]\(([^)]+)\)/)
  return m ? m[1] : null
}

// Mélange déterministe (shuffle) pour l'affichage
function shuffle<T>(arr: T[]): T[] {
  const a = [...arr]
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[a[i], a[j]] = [a[j], a[i]]
  }
  return a
}

// ── QCM (Q) ───────────────────────────────────────────────────────────────

export function QCMInput({ value, onChange, disabled, content }: {
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
  content?: string
}) {
  // Options = lettres A, B, C... une par ligne `- X)` ou `- [ ] X` dans le contenu
  const items = content ? parseListItems(content) : []
  const options = items.length > 0
    ? items.map((_, idx) => String.fromCharCode(65 + idx))
    : ['A', 'B', 'C', 'D', 'E', 'F']
  const toggle = (opt: string) => {
    if (disabled) return
    if (value.includes(opt)) onChange(value.filter((v) => v !== opt))
    else onChange([...value, opt])
  }
  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-2">
        {options.map((opt) => (
          <button
            key={opt}
            onClick={() => toggle(opt)}
            disabled={disabled}
            className={`w-12 h-12 rounded-lg font-bold text-lg transition-colors ${
              value.includes(opt) ? 'bg-brand-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            } disabled:opacity-50`}
          >
            {opt}
          </button>
        ))}
      </div>
      {items.length > 0 && (
        <ul className="text-sm text-gray-600 space-y-1">
          {items.map((item, i) => (
            <li key={i}><strong>{String.fromCharCode(65 + i)}</strong> — {item.replace(/^[A-F]\)\s*/, '')}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Sondage (P) ───────────────────────────────────────────────────────────

export function SondageInput({ value, onChange, disabled, content }: {
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
  content?: string
}) {
  const items = content ? parseListItems(content) : []
  const options = items.length > 0
    ? items.map((_, i) => String.fromCharCode(65 + i))
    : ['A', 'B', 'C', 'D', 'E', 'F']
  return (
    <div>
      <div className="flex flex-wrap gap-2 mb-2">
        {options.map((opt) => (
          <button
            key={opt}
            onClick={() => !disabled && onChange([opt])}
            disabled={disabled}
            className={`w-12 h-12 rounded-lg font-bold text-lg transition-colors ${
              value.includes(opt) ? 'bg-green-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            } disabled:opacity-50`}
          >
            {opt}
          </button>
        ))}
      </div>
      {items.length > 0 && (
        <ul className="text-sm text-gray-600 space-y-1">
          {items.map((item, i) => (
            <li key={i}><strong>{String.fromCharCode(65 + i)}</strong> — {item.replace(/^[A-F]\)\s*/, '')}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ── Texte libre (F) ───────────────────────────────────────────────────────

export function TexteLibreInput({ value, onChange, disabled }: {
  value: string
  onChange: (v: string) => void
  disabled?: boolean
}) {
  return (
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      maxLength={5000}
      rows={5}
      placeholder="Votre réponse..."
      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:bg-gray-50"
    />
  )
}

// ── Nuage de mots (N) ─────────────────────────────────────────────────────

export function NuageMotsInput({ value, onChange, disabled }: {
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
}) {
  const [input, setInput] = useState('')
  const add = () => {
    const w = input.trim()
    if (w && value.length < 5 && !value.includes(w)) {
      onChange([...value, w])
      setInput('')
    }
  }
  return (
    <div>
      <div className="flex gap-2 mb-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); add() } }}
          disabled={disabled || value.length >= 5}
          maxLength={30}
          placeholder="Un mot..."
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:bg-gray-50"
        />
        <button onClick={add} disabled={disabled || !input.trim() || value.length >= 5} className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50">+</button>
      </div>
      <div className="flex flex-wrap gap-2">
        {value.map((w, i) => (
          <span key={i} className="inline-flex items-center gap-1 px-3 py-1 bg-brand-100 text-brand-800 rounded-full text-sm">
            {w}
            {!disabled && <button onClick={() => onChange(value.filter((_, j) => j !== i))} className="text-brand-600 hover:text-brand-800">&times;</button>}
          </span>
        ))}
      </div>
      <p className="text-xs text-gray-400 mt-1">{value.length}/5 mots</p>
    </div>
  )
}

// ── Échelle 1-5 (L) ───────────────────────────────────────────────────────

export function EchelleInput({ value, onChange, disabled }: {
  value: number | null
  onChange: (v: number) => void
  disabled?: boolean
}) {
  return (
    <div className="flex gap-2 justify-center">
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          onClick={() => !disabled && onChange(n)}
          disabled={disabled}
          className={`w-14 h-14 rounded-full font-bold text-xl transition-all ${
            value === n ? 'bg-brand-600 text-white scale-110' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          } disabled:opacity-50`}
        >
          {n}
        </button>
      ))}
    </div>
  )
}

// ── Pin sur image (I) — l'image est extraite du contenu Markdown ──────────

export function PinImageInput({ value, onChange, imageUrl, disabled }: {
  value: { x: number; y: number } | null
  onChange: (v: { x: number; y: number }) => void
  imageUrl: string
  disabled?: boolean
}) {
  const ref = React.useRef<HTMLDivElement>(null)
  if (!imageUrl) return <p className="text-gray-400 text-sm">Aucune image trouvée dans la slide.</p>
  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (disabled || !ref.current) return
    const rect = ref.current.getBoundingClientRect()
    const x = Math.round(((e.clientX - rect.left) / rect.width) * 1000) / 1000
    const y = Math.round(((e.clientY - rect.top) / rect.height) * 1000) / 1000
    onChange({ x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) })
  }
  return (
    <div>
      <div ref={ref} onClick={handleClick} className="relative cursor-crosshair border rounded-lg overflow-hidden inline-block max-w-full">
        <img src={imageUrl} alt="" className="w-full block select-none" draggable={false} />
        {value && (
          <div
            className="absolute w-5 h-5 bg-red-500 rounded-full border-2 border-white shadow-lg -translate-x-1/2 -translate-y-1/2 pointer-events-none"
            style={{ left: `${value.x * 100}%`, top: `${value.y * 100}%` }}
          />
        )}
      </div>
      {value && !disabled && (
        <button onClick={() => onChange({ x: 0, y: 0 })} className="text-xs text-gray-400 mt-1 hover:text-red-500">
          Effacer le point (actuellement x={value.x.toFixed(2)}, y={value.y.toFixed(2)})
        </button>
      )}
      {value && <p className="text-xs text-gray-500 mt-1">Point placé : x={value.x.toFixed(2)}, y={value.y.toFixed(2)}</p>}
    </div>
  )
}

// ── Texte à trous (T) ─────────────────────────────────────────────────────

const TROU_RE = /_{2,}/g

export function TexteTrousInput({ content, value, onChange, disabled }: {
  content: string
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
}) {
  const parts = content.split(TROU_RE)
  const nbTrous = parts.length - 1
  const setTrou = (i: number, val: string) => {
    const next = [...value]
    next[i] = val
    onChange(next)
  }
  return (
    <div className="space-y-3 text-gray-800 leading-relaxed">
      {parts.map((part, i) => (
        <span key={i}>
          <InlineMarkdown text={part} />
          {i < nbTrous && (
            <input
              type="text"
              value={value[i] || ''}
              onChange={(e) => setTrou(i, e.target.value)}
              disabled={disabled}
              placeholder={`mot ${i + 1}`}
              className="inline-block mx-1 px-2 py-1 border-b-2 border-brand-500 bg-brand-50 rounded focus:outline-none focus:border-brand-700 disabled:bg-gray-100 text-center"
              style={{ width: `${Math.max(6, (value[i] || '').length + 4)}ch`, minWidth: '6ch' }}
            />
          )}
        </span>
      ))}
    </div>
  )
}

function InlineMarkdown({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <>
      {lines.map((line, li) => (
        <span key={li}>
          {li > 0 && <br />}
          {renderInline(line)}
        </span>
      ))}
    </>
  )
}

function renderInline(line: string): React.ReactNode {
  const tokens = line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return tokens.map((tok, i) => {
    if (tok.startsWith('**') && tok.endsWith('**')) return <strong key={i}>{tok.slice(2, -2)}</strong>
    if (tok.startsWith('`') && tok.endsWith('`')) return <code key={i} className="bg-gray-100 px-1 rounded font-mono text-sm">{tok.slice(1, -1)}</code>
    if (tok.startsWith('#')) return <strong key={i} className="text-lg">{tok.replace(/^#+\s*/, '')}</strong>
    return <span key={i}>{tok}</span>
  })
}

// ── Ordonner (O) — boutons haut/bas ───────────────────────────────────────

export function OrdreInput({ content, value, onChange, disabled }: {
  content: string
  value: string[]       // ordre actuel des éléments
  onChange: (v: string[]) => void
  disabled?: boolean
}) {
  const items = useMemo(() => parseListItems(content), [content])
  // Initialise l'ordre si vide
  const order = value.length === items.length ? value : items
  const move = (i: number, dir: -1 | 1) => {
    if (disabled) return
    const j = i + dir
    if (j < 0 || j >= order.length) return
    const next = [...order]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }
  return (
    <ol className="space-y-2">
      {order.map((item, i) => (
        <li key={i} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2 border border-gray-200">
          <span className="font-bold text-brand-600 w-6">{i + 1}.</span>
          <span className="flex-1">{item}</span>
          <div className="flex flex-col">
            <button onClick={() => move(i, -1)} disabled={disabled || i === 0} className="text-gray-500 hover:text-brand-600 disabled:opacity-30 text-xs leading-none">▲</button>
            <button onClick={() => move(i, 1)} disabled={disabled || i === order.length - 1} className="text-gray-500 hover:text-brand-600 disabled:opacity-30 text-xs leading-none">▼</button>
          </div>
        </li>
      ))}
    </ol>
  )
}

// ── Classer (R) — select de catégorie par élément ─────────────────────────

export function ClasserInput({ content, value, onChange, disabled }: {
  content: string
  value: Record<string, string>  // { élément: catégorie }
  onChange: (v: Record<string, string>) => void
  disabled?: boolean
}) {
  const cats = useMemo(() => parseCategories(content), [content])
  const items = useMemo(() => parseListItems(content), [content])
  const setCat = (item: string, cat: string) => onChange({ ...value, [item]: cat })
  if (cats.length === 0) return <p className="text-gray-400 text-sm">Aucune catégorie trouvée (utilisez **Nom** sur une ligne seule).</p>
  return (
    <div className="space-y-2">
      {items.map((item, i) => (
        <div key={i} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2 border border-gray-200">
          <span className="flex-1 font-medium">{item}</span>
          <select
            value={value[item] || ''}
            onChange={(e) => !disabled && setCat(item, e.target.value)}
            disabled={disabled}
            className="px-2 py-1 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:bg-gray-100"
          >
            <option value="">— choisir —</option>
            {cats.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      ))}
    </div>
  )
}

// ── Association (A) — select droite pour chaque gauche ───────────────────

export function AssociationInput({ content, value, onChange, disabled }: {
  content: string
  value: Record<string, string>  // { gauche: droite choisie }
  onChange: (v: Record<string, string>) => void
  disabled?: boolean
}) {
  const pairs = useMemo(() => parsePairs(content), [content])
  // Toutes les valeurs de droite, mélangées pour l'affichage
  const rights = useMemo(() => shuffle(pairs.map((p) => p.right)), [content])
  const setRight = (left: string, right: string) => onChange({ ...value, [left]: right })
  if (pairs.length === 0) return <p className="text-gray-400 text-sm">Aucune paire trouvée (format : - gauche =&gt; droite).</p>
  return (
    <div className="space-y-2">
      {pairs.map((p, i) => (
        <div key={i} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-2 border border-gray-200">
          <span className="flex-1 font-medium">{p.left}</span>
          <span className="text-gray-400">→</span>
          <select
            value={value[p.left] || ''}
            onChange={(e) => !disabled && setRight(p.left, e.target.value)}
            disabled={disabled}
            className="px-2 py-1 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:bg-gray-100"
          >
            <option value="">— choisir —</option>
            {rights.map((r, j) => <option key={j} value={r}>{r}</option>)}
          </select>
        </div>
      ))}
    </div>
  )
}

// ── Sélecteur d'exercice générique ────────────────────────────────────────

export function ExerciseInput({
  type, answer, onChange, disabled, content,
}: {
  type: SlideType
  answer: Record<string, unknown>
  onChange: (a: Record<string, unknown>) => void
  disabled?: boolean
  content?: string
}) {
  switch (type) {
    case 'Q':
      return <QCMInput content={content} value={(answer.selected as string[]) || []} onChange={(v) => onChange({ selected: v })} disabled={disabled} />
    case 'P':
      return <SondageInput content={content} value={(answer.selected as string[]) || []} onChange={(v) => onChange({ selected: v })} disabled={disabled} />
    case 'F':
      return <TexteLibreInput value={(answer.text as string) || ''} onChange={(v) => onChange({ text: v })} disabled={disabled} />
    case 'N':
      return <NuageMotsInput value={(answer.words as string[]) || []} onChange={(v) => onChange({ words: v })} disabled={disabled} />
    case 'L':
      return <EchelleInput value={(answer.value as number) ?? null} onChange={(v) => onChange({ value: v })} disabled={disabled} />
    case 'I': {
      const img = content ? parseFirstImage(content) : null
      return <PinImageInput value={(answer.x !== undefined ? { x: answer.x as number, y: answer.y as number } : null)} onChange={(v) => onChange({ x: v.x, y: v.y })} imageUrl={img || ''} disabled={disabled} />
    }
    case 'T':
      return <TexteTrousInput content={content || ''} value={(answer.blanks as string[]) || []} onChange={(v) => onChange({ blanks: v })} disabled={disabled} />
    case 'O':
      return <OrdreInput content={content || ''} value={(answer.order as string[]) || []} onChange={(v) => onChange({ order: v })} disabled={disabled} />
    case 'R':
      return <ClasserInput content={content || ''} value={(answer.categories as Record<string, string>) || {}} onChange={(v) => onChange({ categories: v })} disabled={disabled} />
    case 'A':
      return <AssociationInput content={content || ''} value={(answer.pairs as Record<string, string>) || {}} onChange={(v) => onChange({ pairs: v })} disabled={disabled} />
    default:
      return null
  }
}

export function exerciseTypeLabel(type: string): string {
  return SLIDE_TYPE_LABELS[type as SlideType] || type
}
