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

// ── QCM (Q) — cartes à cocher style Wooclap ───────────────────────────────

// Parse les options : lignes `- A) texte` ou `- [ ] texte` ou `- texte`
export function parseOptions(content: string): { letter: string; text: string }[] {
  const lines = content.split('\n')
    .map((l) => l.replace(/^\s*(?:[-*+]\s+(?:\[[ xX]\]\s+)?)?/, '').trim())
    .filter((l) => l.length > 0 && !l.startsWith('#'))
  return lines.map((l, i) => {
    const m = l.match(/^([A-Z])\)\s*(.+)$/)
    if (m) return { letter: m[1], text: m[2] }
    return { letter: String.fromCharCode(65 + i), text: l }
  })
}

export function QCMInput({ value, onChange, disabled, content }: {
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
  content?: string
}) {
  const options = content ? parseOptions(content) : []
  const toggle = (letter: string) => {
    if (disabled) return
    if (value.includes(letter)) onChange(value.filter((v) => v !== letter))
    else onChange([...value, letter])
  }
  if (options.length === 0) return <p className="text-gray-400 text-sm">Aucune option trouvée (lignes - A) ... dans la slide).</p>
  return (
    <div className="space-y-2">
      {options.map((opt) => {
        const selected = value.includes(opt.letter)
        return (
          <button
            key={opt.letter}
            onClick={() => toggle(opt.letter)}
            disabled={disabled}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl border-2 text-left transition-all ${
              selected
                ? 'border-brand-500 bg-brand-50 text-brand-800'
                : 'border-gray-200 bg-white hover:border-gray-400'
            } disabled:opacity-60`}
          >
            <span className={`w-7 h-7 rounded-md border-2 flex items-center justify-center font-bold text-sm shrink-0 ${
              selected ? 'border-brand-600 bg-brand-600 text-white' : 'border-gray-300 text-gray-500'
            }`}>
              {selected ? '✓' : opt.letter}
            </span>
            <span className="flex-1">{opt.text}</span>
          </button>
        )
      })}
    </div>
  )
}

// ── Sondage (P) — un seul choix, style radio Wooclap ──────────────────────

export function SondageInput({ value, onChange, disabled, content }: {
  value: string[]
  onChange: (v: string[]) => void
  disabled?: boolean
  content?: string
}) {
  const options = content ? parseOptions(content) : []
  if (options.length === 0) return <p className="text-gray-400 text-sm">Aucune option trouvée.</p>
  return (
    <div className="space-y-2">
      {options.map((opt) => {
        const selected = value.includes(opt.letter)
        return (
          <button
            key={opt.letter}
            onClick={() => !disabled && onChange([opt.letter])}
            disabled={disabled}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl border-2 text-left transition-all ${
              selected
                ? 'border-green-500 bg-green-50 text-green-800'
                : 'border-gray-200 bg-white hover:border-gray-400'
            } disabled:opacity-60`}
          >
            <span className={`w-7 h-7 rounded-full border-2 flex items-center justify-center font-bold text-sm shrink-0 ${
              selected ? 'border-green-600 bg-green-600 text-white' : 'border-gray-300 text-gray-500'
            }`}>
              {opt.letter}
            </span>
            <span className="flex-1">{opt.text}</span>
          </button>
        )
      })}
    </div>
  )
}

// ── Texte libre (F) — avec compteur ──────────────────────────────────────

export function TexteLibreInput({ value, onChange, disabled }: {
  value: string
  onChange: (v: string) => void
  disabled?: boolean
}) {
  return (
    <div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        maxLength={5000}
        rows={6}
        placeholder="Votre réponse..."
        className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 disabled:bg-gray-50 resize-y"
      />
      <p className="text-xs text-gray-400 text-right mt-1">{value.length}/5000</p>
    </div>
  )
}

// ── Nuage de mots (N) — saisie inline dans un champ avec tags ─────────────

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
      <div
        className={`flex flex-wrap items-center gap-1 px-2 py-2 border-2 rounded-xl focus-within:ring-2 focus-within:ring-brand-500 focus-within:border-brand-500 ${
          disabled ? 'bg-gray-50 border-gray-200' : 'border-gray-300 bg-white'
        }`}
        onClick={(e) => { const inp = e.currentTarget.querySelector('input'); inp?.focus() }}
      >
        {value.map((w, i) => (
          <span key={i} className="inline-flex items-center gap-1 px-3 py-1 bg-brand-100 text-brand-800 rounded-full text-sm font-medium">
            {w}
            {!disabled && (
              <button onClick={(e) => { e.stopPropagation(); onChange(value.filter((_, j) => j !== i)) }} className="text-brand-500 hover:text-red-500 font-bold">&times;</button>
            )}
          </span>
        ))}
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add() }
            if (e.key === 'Backspace' && !input && value.length > 0) onChange(value.slice(0, -1))
          }}
          disabled={disabled || value.length >= 5}
          maxLength={30}
          placeholder={value.length === 0 ? 'Tapez un mot, Entrée pour ajouter...' : ''}
          className="flex-1 min-w-[120px] px-1 py-1 outline-none bg-transparent text-sm disabled:cursor-not-allowed"
        />
      </div>
      <p className="text-xs text-gray-400 mt-1">{value.length}/5 mots — Entrée ou virgule pour valider</p>
    </div>
  )
}

// ── Échelle 1-5 (L) — avec labels ─────────────────────────────────────────

const L_ECHELLE_LABELS = ['Pas du tout', 'Plutôt non', 'Neutre', 'Plutôt oui', 'Tout à fait']

export function EchelleInput({ value, onChange, disabled }: {
  value: number | null
  onChange: (v: number) => void
  disabled?: boolean
}) {
  return (
    <div>
      <div className="flex gap-2 justify-center">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            onClick={() => !disabled && onChange(n)}
            disabled={disabled}
            className={`w-14 h-14 rounded-full font-bold text-xl transition-all ${
              value === n ? 'bg-brand-600 text-white scale-110 shadow-lg' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            } disabled:opacity-50`}
          >
            {n}
          </button>
        ))}
      </div>
      <div className="flex justify-between mt-2 text-xs text-gray-500 px-1">
        <span>{L_ECHELLE_LABELS[0]}</span>
        <span className="font-medium text-brand-600">{value ? L_ECHELLE_LABELS[value - 1] : ''}</span>
        <span>{L_ECHELLE_LABELS[4]}</span>
      </div>
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

// ── Drag & drop natif HTML5 ───────────────────────────────────────────────

function DraggableItem({
  label, index, onDragStart, onDragOver, onDrop, isDragging, isDropTarget, disabled, className = '',
}: {
  label: string
  index: number
  onDragStart: (i: number) => void
  onDragOver: (e: React.DragEvent, i: number) => void
  onDrop: (i: number) => void
  isDragging: boolean
  isDropTarget: boolean
  disabled?: boolean
  className?: string
}) {
  return (
    <div
      draggable={!disabled}
      onDragStart={(e) => { e.dataTransfer.effectAllowed = 'move'; onDragStart(index) }}
      onDragOver={(e) => onDragOver(e, index)}
      onDrop={(e) => { e.preventDefault(); onDrop(index) }}
      className={`px-4 py-3 rounded-lg border-2 font-medium transition-all select-none ${
        disabled ? 'opacity-60 cursor-not-allowed' : 'cursor-grab active:cursor-grabbing'
      } ${
        isDragging ? 'opacity-40 border-dashed border-gray-400' : ''
      } ${
        isDropTarget ? 'border-brand-500 bg-brand-50 scale-[1.02]' : 'border-gray-200 bg-white hover:border-gray-400'
      } ${className}`}
    >
      {label}
    </div>
  )
}

// ── Ordonner (O) — drag & drop vertical type Wooclap ──────────────────────

export function OrdreInput({ content, value, onChange, disabled }: {
  content: string
  value: string[]       // ordre actuel des éléments
  onChange: (v: string[]) => void
  disabled?: boolean
}) {
  const items = useMemo(() => parseListItems(content), [content])
  const order = value.length === items.length ? value : items
  const [dragIndex, setDragIndex] = useState<number | null>(null)
  const [dropIndex, setDropIndex] = useState<number | null>(null)

  const handleDrop = (targetIndex: number) => {
    if (disabled || dragIndex === null || dragIndex === targetIndex) return
    const next = [...order]
    const [moved] = next.splice(dragIndex, 1)
    next.splice(targetIndex, 0, moved)
    onChange(next)
    setDragIndex(null)
    setDropIndex(null)
  }

  return (
    <ol className="space-y-2">
      {order.map((item, i) => (
        <li key={`${item}-${i}`} className="flex items-center gap-2">
          <span className="font-bold text-brand-600 w-6 text-center">{i + 1}.</span>
          <div className="flex-1">
            <DraggableItem
              label={item}
              index={i}
              onDragStart={setDragIndex}
              onDragOver={(e, idx) => { e.preventDefault(); setDropIndex(idx) }}
              onDrop={handleDrop}
              isDragging={dragIndex === i}
              isDropTarget={dropIndex === i && dragIndex !== i}
              disabled={disabled}
            />
          </div>
          <span className="text-gray-300 text-lg select-none">⠿</span>
        </li>
      ))}
      <p className="text-xs text-gray-400 mt-2">Glissez-déposez les éléments pour les réordonner.</p>
    </ol>
  )
}

// ── Classer (R) — drag & drop dans des colonnes de catégories ─────────────

export function ClasserInput({ content, value, onChange, disabled }: {
  content: string
  value: Record<string, string>  // { élément: catégorie } — '' = non classé
  onChange: (v: Record<string, string>) => void
  disabled?: boolean
}) {
  const cats = useMemo(() => parseCategories(content), [content])
  const allItems = useMemo(() => parseListItems(content), [content])
  const [dragItem, setDragItem] = useState<string | null>(null)
  const [dropCat, setDropCat] = useState<string | null>(null)

  // Zone "à classer" = éléments sans catégorie
  const unclassified = allItems.filter((it) => !value[it])
  const byCat = (cat: string) => allItems.filter((it) => value[it] === cat)

  const assign = (item: string, cat: string) => {
    if (disabled) return
    const next = { ...value }
    if (cat === '') delete next[item]
    else next[item] = cat
    onChange(next)
    setDragItem(null)
    setDropCat(null)
  }

  if (cats.length === 0) return <p className="text-gray-400 text-sm">Aucune catégorie trouvée (utilisez **Nom** sur une ligne seule).</p>

  const renderItem = (item: string) => (
    <DraggableItem
      key={item}
      label={item}
      index={0}
      onDragStart={() => setDragItem(item)}
      onDragOver={(e) => e.preventDefault()}
      onDrop={() => {}}
      isDragging={dragItem === item}
      isDropTarget={false}
      disabled={disabled}
      className="text-sm !py-2"
    />
  )

  const DropZone = ({ cat, children, label }: { cat: string; children: React.ReactNode; label: string }) => (
    <div
      onDragOver={(e) => { e.preventDefault(); setDropCat(cat) }}
      onDragLeave={() => setDropCat((c) => (c === cat ? null : c))}
      onDrop={(e) => { e.preventDefault(); if (dragItem) assign(dragItem, cat) }}
      className={`rounded-xl border-2 p-3 min-h-[80px] transition-colors ${
        dropCat === cat ? 'border-brand-500 bg-brand-50' : 'border-gray-200 bg-gray-50'
      }`}
    >
      <p className="text-xs font-semibold text-gray-500 uppercase mb-2">{label}</p>
      <div className="space-y-1">{children}</div>
      {React.Children.count(children) === 0 && (
        <p className="text-xs text-gray-300 italic">Déposez ici</p>
      )}
    </div>
  )

  return (
    <div className="space-y-3">
      {/* Zone à classer */}
      <DropZone cat="" label="À classer">
        {unclassified.map(renderItem)}
      </DropZone>
      {/* Colonnes par catégorie */}
      <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.min(cats.length, 3)}, 1fr)` }}>
        {cats.map((cat) => (
          <DropZone key={cat} cat={cat} label={cat}>
            {byCat(cat).map(renderItem)}
          </DropZone>
        ))}
      </div>
      <p className="text-xs text-gray-400">Glissez-déposez chaque élément dans sa catégorie.</p>
    </div>
  )
}

// ── Association (A) — interface type Wooclap : deux colonnes + liens SVG ──
// Clic sur un élément de gauche, puis sur un élément de droite pour lier.
// Un lien existant peut être supprimé en cliquant dessus.

export function AssociationInput({ content, value, onChange, disabled }: {
  content: string
  value: Record<string, string>  // { gauche: droite choisie }
  onChange: (v: Record<string, string>) => void
  disabled?: boolean
}) {
  const pairs = useMemo(() => parsePairs(content), [content])
  // Droites mélangées pour l'affichage (une seule fois par content)
  const rights = useMemo(() => shuffle(pairs.map((p) => p.right)), [content])
  const [selectedLeft, setSelectedLeft] = useState<string | null>(null)
  const leftRefs = React.useRef<Record<string, HTMLButtonElement | null>>({})
  const rightRefs = React.useRef<Record<string, HTMLButtonElement | null>>({})
  const containerRef = React.useRef<HTMLDivElement>(null)
  const [, forceRender] = useState(0)

  // Recalcule les positions des lignes après chaque rendu
  React.useEffect(() => {
    forceRender((n) => n + 1)
  }, [value, selectedLeft])

  if (pairs.length === 0) return <p className="text-gray-400 text-sm">Aucune paire trouvée (format : - gauche =&gt; droite).</p>

  // Droite déjà prise par une autre gauche ?
  const isRightTaken = (r: string) => Object.values(value).includes(r)

  const link = (left: string, right: string) => {
    if (disabled) return
    // Si la droite est déjà liée à une autre gauche, on écrase
    const next = { ...value }
    for (const k of Object.keys(next)) if (next[k] === right) delete next[k]
    next[left] = right
    onChange(next)
    setSelectedLeft(null)
  }

  const unlink = (left: string) => {
    if (disabled) return
    const next = { ...value }
    delete next[left]
    onChange(next)
  }

  const handleLeftClick = (left: string) => {
    if (disabled) return
    setSelectedLeft(selectedLeft === left ? null : left)
  }

  const handleRightClick = (right: string) => {
    if (disabled || !selectedLeft) return
    link(selectedLeft, right)
  }

  // Calcul des lignes SVG entre les éléments liés
  const getLinkCoords = (left: string, right: string) => {
    const l = leftRefs.current[left]
    const r = rightRefs.current[right]
    const c = containerRef.current
    if (!l || !r || !c) return null
    const lr = l.getBoundingClientRect()
    const rr = r.getBoundingClientRect()
    const cr = c.getBoundingClientRect()
    return {
      x1: lr.right - cr.left,
      y1: lr.top + lr.height / 2 - cr.top,
      x2: rr.left - cr.left,
      y2: rr.top + rr.height / 2 - cr.top,
    }
  }

  const links = Object.entries(value)
    .map(([l, r]) => ({ left: l, right: r, coords: getLinkCoords(l, r) }))
    .filter((x) => x.coords)

  return (
    <div ref={containerRef} className="relative">
      {/* Lignes SVG de liaison */}
      <svg className="absolute inset-0 pointer-events-none" style={{ width: '100%', height: '100%', zIndex: 0 }}>
        {links.map((lk, i) => lk.coords && (
          <line
            key={i}
            x1={lk.coords.x1} y1={lk.coords.y1}
            x2={lk.coords.x2} y2={lk.coords.y2}
            stroke="#3380fc" strokeWidth="3" strokeLinecap="round"
          />
        ))}
        {/* Ligne temporaire vers la sélection en cours */}
        {selectedLeft && (() => {
          const l = leftRefs.current[selectedLeft]
          const c = containerRef.current
          if (!l || !c) return null
          const lr = l.getBoundingClientRect()
          const cr = c.getBoundingClientRect()
          return (
            <line
              x1={lr.right - cr.left} y1={lr.top + lr.height / 2 - cr.top}
              x2={lr.right - cr.left + 40} y2={lr.top + lr.height / 2 - cr.top}
              stroke="#59a3ff" strokeWidth="2" strokeDasharray="4 3"
            />
          )
        })()}
      </svg>

      <div className="flex gap-8 relative" style={{ zIndex: 1 }}>
        {/* Colonne gauche */}
        <div className="flex-1 space-y-2">
          <p className="text-xs text-gray-400 uppercase mb-1">Éléments</p>
          {pairs.map((p, i) => {
            const isSelected = selectedLeft === p.left
            const isLinked = !!value[p.left]
            return (
              <button
                key={i}
                ref={(el) => { leftRefs.current[p.left] = el }}
                onClick={() => handleLeftClick(p.left)}
                disabled={disabled}
                className={`w-full text-left px-4 py-3 rounded-lg border-2 font-medium transition-all ${
                  isSelected
                    ? 'border-brand-500 bg-brand-50 text-brand-700'
                    : isLinked
                      ? 'border-green-400 bg-green-50 text-green-800'
                      : 'border-gray-200 bg-white hover:border-gray-400'
                } disabled:opacity-60`}
              >
                {p.left}
                {isLinked && (
                  <span
                    role="button"
                    onClick={(e) => { e.stopPropagation(); unlink(p.left) }}
                    className="float-right text-green-500 hover:text-red-500 text-xs"
                    title="Supprimer le lien"
                  >✕</span>
                )}
              </button>
            )
          })}
        </div>

        {/* Colonne droite */}
        <div className="flex-1 space-y-2">
          <p className="text-xs text-gray-400 uppercase mb-1">Réponses</p>
          {rights.map((r, i) => {
            const taken = isRightTaken(r)
            const linkedTo = Object.entries(value).find(([, rv]) => rv === r)?.[0]
            return (
              <button
                key={i}
                ref={(el) => { rightRefs.current[r] = el }}
                onClick={() => handleRightClick(r)}
                disabled={disabled || (taken && linkedTo !== selectedLeft)}
                className={`w-full text-left px-4 py-3 rounded-lg border-2 transition-all ${
                  taken
                    ? 'border-green-400 bg-green-50 text-green-800 opacity-70'
                    : selectedLeft
                      ? 'border-brand-300 bg-white hover:border-brand-500 hover:bg-brand-50 cursor-pointer'
                      : 'border-gray-200 bg-gray-50 text-gray-500'
                } disabled:cursor-not-allowed`}
              >
                {r}
              </button>
            )
          })}
        </div>
      </div>

      <p className="text-xs text-gray-400 mt-3">
        {selectedLeft
          ? `Sélectionnez une réponse pour « ${selectedLeft} » →`
          : 'Cliquez sur un élément à gauche, puis sur sa réponse à droite.'}
      </p>
      {/* Force re-render pour recalculer les lignes après changement */}
      {void forceRender}
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
