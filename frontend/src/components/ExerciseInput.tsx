// Composants d'interaction pour chaque type de slide exercice.
// Chaque composant reçoit la valeur courante et un callback onChange.
import React, { useState } from 'react'
import { SLIDE_TYPE_LABELS, type SlideType } from '@/types/api'

// ── QCM (Q) : sélection multiple ─────────────────────────────────────────

export function QCMInput({
  value, onChange, disabled,
}: {
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
}) {
  // Les options sont parsées depuis le contenu Markdown (lignes commençant par - [ ] ou -)
  // En l'absence d'options explicites, on laisse le formateur les définir dans le texte.
  // Pour simplifier, on propose une liste d'options A-F que le formateur peut adapter.
  const options = ['A', 'B', 'C', 'D', 'E', 'F']
  const toggle = (opt: string) => {
    if (disabled) return
    if (value.includes(opt)) onChange(value.filter((v) => v !== opt))
    else onChange([...value, opt])
  }
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => toggle(opt)}
          disabled={disabled}
          className={`w-12 h-12 rounded-lg font-bold text-lg transition-colors ${
            value.includes(opt)
              ? 'bg-brand-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          } disabled:opacity-50`}
        >
          {opt}
        </button>
      ))}
    </div>
  )
}

// ── Sondage (P) : un seul choix ───────────────────────────────────────────

export function SondageInput({
  value, onChange, disabled,
}: {
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
}) {
  const options = ['A', 'B', 'C', 'D', 'E', 'F']
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((opt) => (
        <button
          key={opt}
          onClick={() => !disabled && onChange([opt])}
          disabled={disabled}
          className={`w-12 h-12 rounded-lg font-bold text-lg transition-colors ${
            value.includes(opt)
              ? 'bg-green-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          } disabled:opacity-50`}
        >
          {opt}
        </button>
      ))}
    </div>
  )
}

// ── Texte libre (F) ───────────────────────────────────────────────────────

export function TexteLibreInput({
  value, onChange, disabled,
}: {
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

export function NuageMotsInput({
  value, onChange, disabled,
}: {
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
        <button
          onClick={add}
          disabled={disabled || !input.trim() || value.length >= 5}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg hover:bg-brand-700 disabled:opacity-50"
        >
          +
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {value.map((w, i) => (
          <span key={i} className="inline-flex items-center gap-1 px-3 py-1 bg-brand-100 text-brand-800 rounded-full text-sm">
            {w}
            {!disabled && (
              <button onClick={() => onChange(value.filter((_, j) => j !== i))} className="text-brand-600 hover:text-brand-800">&times;</button>
            )}
          </span>
        ))}
      </div>
      <p className="text-xs text-gray-400 mt-1">{value.length}/5 mots</p>
    </div>
  )
}

// ── Échelle 1-5 (L) ───────────────────────────────────────────────────────

export function EchelleInput({
  value, onChange, disabled,
}: {
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
            value === n
              ? 'bg-brand-600 text-white scale-110'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          } disabled:opacity-50`}
        >
          {n}
        </button>
      ))}
    </div>
  )
}

// ── Pin sur image (I) ─────────────────────────────────────────────────────

export function PinImageInput({
  value, onChange, imageUrl, disabled,
}: {
  value: { x: number; y: number } | null
  onChange: (v: { x: number; y: number }) => void
  imageUrl: string
  disabled?: boolean
}) {
  const ref = React.useRef<HTMLDivElement>(null)
  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (disabled || !ref.current) return
    const rect = ref.current.getBoundingClientRect()
    const x = Math.round(((e.clientX - rect.left) / rect.width) * 1000) / 1000
    const y = Math.round(((e.clientY - rect.top) / rect.height) * 1000) / 1000
    onChange({ x: Math.max(0, Math.min(1, x)), y: Math.max(0, Math.min(1, y)) })
  }
  return (
    <div
      ref={ref}
      onClick={handleClick}
      className="relative cursor-crosshair border rounded-lg overflow-hidden"
      style={{ maxWidth: '100%' }}
    >
      <img src={imageUrl} alt="" className="w-full block" draggable={false} />
      {value && (
        <div
          className="absolute w-4 h-4 bg-red-500 rounded-full border-2 border-white shadow-lg -translate-x-1/2 -translate-y-1/2"
          style={{ left: `${value.x * 100}%`, top: `${value.y * 100}%` }}
        />
      )}
    </div>
  )
}

// ── Texte à trous (T) ─────────────────────────────────────────────────────
// Parse le contenu Markdown, trouve les trous (___ ou ____ etc.) et affiche
// le texte avec un champ input inline à la place de chaque trou.

const TROU_RE = /_{2,}/g

export function TexteTrousInput({
  content, value, onChange, disabled,
}: {
  content: string
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
}) {
  // Découpe le contenu autour des trous
  const parts = content.split(TROU_RE)
  const nbTrous = parts.length - 1

  const setTrou = (i: number, val: string) => {
    const next = [...value]
    next[i] = val
    onChange(next)
  }

  // Rendu simple : on affiche le texte ligne par ligne, les trous deviennent des inputs
  return (
    <div className="space-y-3 text-gray-800 leading-relaxed">
      {parts.map((part, i) => (
        <span key={i}>
          {/* Rendu minimal du markdown inline : gras, code, sauts de ligne */}
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

// Rendu minimal inline : **gras**, `code`, # titres, - listes, sauts de ligne
function InlineMarkdown({ text }: { text: string }) {
  // Découpe en lignes pour gérer les titres/listes
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
  // Sépare le markdown inline : **gras**, `code`
  const tokens = line.split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
  return tokens.map((tok, i) => {
    if (tok.startsWith('**') && tok.endsWith('**')) return <strong key={i}>{tok.slice(2, -2)}</strong>
    if (tok.startsWith('`') && tok.endsWith('`')) return <code key={i} className="bg-gray-100 px-1 rounded font-mono text-sm">{tok.slice(1, -1)}</code>
    // Titres
    if (tok.startsWith('#')) return <strong key={i} className="text-lg">{tok.replace(/^#+\s*/, '')}</strong>
    return <span key={i}>{tok}</span>
  })
}

// ── Sélecteur d'exercice générique ────────────────────────────────────────

export function ExerciseInput({
  type, answer, onChange, disabled, imageUrl, content,
}: {
  type: SlideType
  answer: Record<string, unknown>
  onChange: (a: Record<string, unknown>) => void
  disabled?: boolean
  imageUrl?: string
  content?: string
}) {
  switch (type) {
    case 'Q':
      return <QCMInput value={(answer.selected as string[]) || []} onChange={(v) => onChange({ selected: v })} disabled={disabled} />
    case 'P':
      return <SondageInput value={(answer.selected as string[]) || []} onChange={(v) => onChange({ selected: v })} disabled={disabled} />
    case 'F':
      return <TexteLibreInput value={(answer.text as string) || ''} onChange={(v) => onChange({ text: v })} disabled={disabled} />
    case 'N':
      return <NuageMotsInput value={(answer.words as string[]) || []} onChange={(v) => onChange({ words: v })} disabled={disabled} />
    case 'L':
      return <EchelleInput value={(answer.value as number) ?? null} onChange={(v) => onChange({ value: v })} disabled={disabled} />
    case 'I':
      return <PinImageInput value={(answer.x !== undefined ? { x: answer.x as number, y: answer.y as number } : null)} onChange={(v) => onChange({ x: v.x, y: v.y })} imageUrl={imageUrl || ''} disabled={disabled} />
    case 'T':
      return <TexteTrousInput content={content || ''} value={(answer.blanks as string[]) || []} onChange={(v) => onChange({ blanks: v })} disabled={disabled} />
    case 'A':
    case 'O':
    case 'R':
      // Association / Ordre / Catégories : interface simplifiée en texte libre pour l'instant
      return <TexteLibreInput value={(answer.text as string) || ''} onChange={(v) => onChange({ text: v })} disabled={disabled} />
    default:
      return null
  }
}

export function exerciseTypeLabel(type: string): string {
  return SLIDE_TYPE_LABELS[type as SlideType] || type
}
