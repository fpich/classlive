// Éditeur de slides : liste, création, édition Markdown, médias.
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { Button, Card, Input, Modal, Spinner, Badge } from '@/components/UI'
import Markdown from '@/components/Markdown'
import { SLIDE_TYPE_LABELS, type SlideType } from '@/types/api'

// Modèles de contenu pré-remplis à la création d'une slide exercice.
const SLIDE_TEMPLATES: Record<SlideType, string> = {
  C: '# Titre\n\nContenu de la slide…',
  Q: '# Question\n\n- A) Première proposition\n- B) Deuxième proposition\n- C) Troisième proposition\n- D) Quatrième proposition',
  P: '# Sondage\n\n- A) Première option\n- B) Deuxième option\n- C) Troisième option',
  A: '# Association\n\n- Terme de gauche => terme de droite\n- Autre terme => autre définition',
  O: '# Mettre dans l\'ordre\n\n- Premier élément\n- Deuxième élément\n- Troisième élément',
  R: '# Classer dans les catégories\n\n**Catégorie 1**\n**Catégorie 2**\n\n- Élément à classer\n- Autre élément',
  T: '# Texte à trous\n\nComplétez la phrase avec le mot manquant : ____.',
  F: '# Texte libre\n\nRédigez votre réponse ici.',
  N: '# Nuage de mots\n\nDonnez jusqu\'à 5 mots-clés.',
  L: '# Échelle\n\nIndiquez votre niveau de 1 à 5.',
  I: '# Pin sur image\n\n![image](url)',
}

// Format du corrigé attendu par type de slide (stocké dans le frontmatter
// `classlive_answer`). Aide affichée dans l'éditeur de corrigé.
const ANSWER_HELP: Record<SlideType, string> = {
  C: 'Slide de contenu : pas de corrigé.',
  Q: 'QCM — options correctes, ex. : {selected: [B, D]}',
  P: 'Sondage — pas de bonne réponse (laisser vide).',
  A: 'Association — paires, ex. : {pairs: {gauche: droite, x: y}}',
  O: 'Ordre — ex. : {order: [Premier, Deuxième, Troisième]}',
  R: 'Classement — ex. : {categories: {élément: Catégorie1}}',
  T: 'Texte à trous — ex. : {blanks: [mot1, mot2]}',
  F: 'Texte libre — ex. : {text: "réponse attendue"}',
  N: 'Nuage de mots — ex. : {words: [mot1, mot2]}',
  L: 'Échelle — ex. : {value: 3}',
  I: 'Pin image — ex. : {x: 0.5, y: 0.5}',
}

// Extrait la valeur `classlive_answer` du frontmatter YAML d'un contenu.
function parseAnswerKey(content: string): string {
  if (!content.startsWith('---\n')) return ''
  const end = content.indexOf('\n---\n', 4)
  if (end === -1) return ''
  const header = content.slice(4, end)
  const m = header.match(/^\s*classlive_answer\s*:\s*(.*)$/m)
  return m ? m[1].trim() : ''
}

// Injecte (ou remplace) la valeur `classlive_answer` dans le frontmatter.
// Si le contenu n'a pas de frontmatter, en crée un. Retourne le nouveau contenu.
function injectAnswerKey(content: string, answer: string): string {
  const value = answer.trim()
  const line = value ? `classlive_answer: ${value}` : ''
  if (!content.startsWith('---\n')) {
    return value ? `---\n${line}\n---\n${content}` : content
  }
  const end = content.indexOf('\n---\n', 4)
  if (end === -1) return content
  const header = content.slice(4, end)
  const body = content.slice(end + 5)
  const lines = header.split('\n')
  const kept = lines.filter((l) => !/^\s*classlive_answer\s*:/.test(l))
  const newHeader = value ? [...kept, line].join('\n') : kept.join('\n')
  return `---\n${newHeader}\n---\n${body}`
}

export default function EditorPage() {
  const { group = '', event = '' } = useParams()
  const navigate = useNavigate()
  const [slides, setSlides] = useState<string[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [newTitle, setNewTitle] = useState('')
  const [newType, setNewType] = useState<SlideType>('C')
  const [media, setMedia] = useState<string[]>([])
  const [preview, setPreview] = useState(true)
  const [answerKey, setAnswerKey] = useState('')
  const [showAnswer, setShowAnswer] = useState(false)

  const load = async () => {
    try {
      setLoading(true)
      const [s, m] = await Promise.all([
        api.listSlides(group, event),
        api.listMedia(group, event),
      ])
      setSlides(s.slides)
      setMedia(m.files)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [group, event])

  const selectSlide = async (slide: string) => {
    try {
      const res = await api.getSlide(group, event, slide)
      setSelected(slide)
      setContent(res.content)
      setAnswerKey(parseAnswerKey(res.content))
      setShowAnswer(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    }
  }

  const saveContent = async () => {
    if (!selected) return
    try {
      setSaving(true)
      await api.updateSlideContent(group, event, selected, content)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    } finally {
      setSaving(false)
    }
  }

  // Enregistre le corrigé : injecte classlive_answer dans le frontmatter puis sauvegarde.
  const saveAnswer = async () => {
    if (!selected) return
    try {
      setSaving(true)
      const updated = injectAnswerKey(content, answerKey)
      setContent(updated)
      await api.updateSlideContent(group, event, selected, updated)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    } finally {
      setSaving(false)
    }
  }

  const createSlide = async () => {
    if (!newTitle.trim()) return
    try {
      const res = await api.createSlide(group, event, { title: newTitle.trim(), slide_type: newType, content: SLIDE_TEMPLATES[newType] })
      setNewTitle('')
      setShowNew(false)
      load()
      selectSlide(res.slide)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    }
  }

  const deleteSlide = async (slide: string) => {
    if (!confirm(`Supprimer ${slide} ?`)) return
    try {
      await api.deleteSlide(group, event, slide)
      if (selected === slide) { setSelected(null); setContent('') }
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    }
  }

  const slideType = (name: string) => name.match(/_([CAORQTFNPLI])_/)?.[1] || 'C'

  if (loading) return <div className="min-h-screen flex items-center justify-center"><Spinner size="lg" /></div>

  return (
    <div className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-white border-b border-gray-200 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/home')} className="text-gray-500 hover:text-gray-700">&larr;</button>
          <h1 className="font-semibold text-gray-800">{group} / {event}</h1>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => navigate(`/live/${encodeURIComponent(group)}/${encodeURIComponent(event)}`)}>
            Lancer un Live
          </Button>
          <Button size="sm" onClick={() => setShowNew(true)}>+ Slide</Button>
        </div>
      </header>

      {error && (
        <div className="mx-6 mt-3 p-3 bg-red-50 text-red-700 rounded-lg text-sm flex justify-between">
          {error}
          <button onClick={() => setError('')}>&times;</button>
        </div>
      )}

      <div className="flex-1 flex overflow-hidden">
        {/* Liste des slides */}
        <div className="w-72 border-r border-gray-200 bg-white overflow-y-auto p-3 space-y-1">
          {slides.length === 0 && <p className="text-sm text-gray-400 p-2">Aucune slide</p>}
          {slides.map((s) => (
            <button
              key={s}
              onClick={() => selectSlide(s)}
              className={`w-full text-left px-3 py-2 rounded-lg text-sm flex items-center gap-2 ${
                selected === s ? 'bg-brand-50 text-brand-700' : 'hover:bg-gray-50'
              }`}
            >
              <Badge color={slideType(s) === 'C' ? 'gray' : 'blue'}>{slideType(s)}</Badge>
              <span className="truncate">{s}</span>
              <span
                role="button"
                onClick={(e) => { e.stopPropagation(); deleteSlide(s) }}
                className="ml-auto text-gray-300 hover:text-red-500"
              >&times;</span>
            </button>
          ))}
        </div>

        {/* Éditeur */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {selected ? (
            <>
              <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 bg-white">
                <div className="flex items-center gap-2">
                  <Badge color="blue">{SLIDE_TYPE_LABELS[slideType(selected) as SlideType]}</Badge>
                  <span className="font-medium text-sm">{selected}</span>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" variant={preview ? 'primary' : 'ghost'} onClick={() => setPreview(true)}>Aperçu</Button>
                  <Button size="sm" variant={!preview ? 'primary' : 'ghost'} onClick={() => setPreview(false)}>Markdown</Button>
                  {slideType(selected) !== 'C' && (
                    <Button size="sm" variant={showAnswer ? 'primary' : 'ghost'} onClick={() => setShowAnswer(!showAnswer)}>
                      Corrigé
                    </Button>
                  )}
                  <Button size="sm" onClick={saveContent} disabled={saving}>
                    {saving ? <Spinner size="sm" /> : 'Enregistrer'}
                  </Button>
                </div>
              </div>
              {showAnswer && (
                <div className="px-4 py-3 border-b border-gray-200 bg-amber-50">
                  <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium text-gray-700">
                      Bonnes réponses (corrigé) — {SLIDE_TYPE_LABELS[slideType(selected) as SlideType]}
                    </label>
                    <span className="text-xs text-gray-500">{answerKey ? 'Corrigé défini' : 'Aucun corrigé'}</span>
                  </div>
                  <p className="text-xs text-gray-500 mb-2">{ANSWER_HELP[slideType(selected) as SlideType]}</p>
                  <div className="flex gap-2">
                    <Input
                      value={answerKey}
                      onChange={setAnswerKey}
                      placeholder="ex. {selected: [B]}"
                      className="flex-1 font-mono text-sm"
                    />
                    <Button size="sm" onClick={saveAnswer} disabled={saving}>
                      {saving ? <Spinner size="sm" /> : 'Enregistrer le corrigé'}
                    </Button>
                  </div>
                  <p className="text-xs text-gray-400 mt-2">
                    Le corrigé est stocké dans le frontmatter (classlive_answer) et n'est jamais envoyé aux étudiants.
                    Il sert à afficher la correction en fin de question.
                  </p>
                </div>
              )}
              <div className="flex-1 overflow-y-auto p-6">
                {preview ? (
                  <Card><Markdown content={content} /></Card>
                ) : (
                  <textarea
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    className="w-full h-full p-4 font-mono text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500 resize-none"
                    placeholder="Contenu Markdown..."
                  />
                )}
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center text-gray-400">
              Sélectionnez une slide ou créez-en une
            </div>
          )}
        </div>

        {/* Médias */}
        <div className="w-56 border-l border-gray-200 bg-white p-3 overflow-y-auto">
          <h3 className="font-medium text-sm text-gray-700 mb-2">Médias ({media.length})</h3>
          {media.length === 0 && <p className="text-xs text-gray-400">Aucun média</p>}
          {media.map((f) => (
            <div key={f} className="text-xs text-gray-600 truncate py-1" title={f}>{f}</div>
          ))}
        </div>
      </div>

      <Modal open={showNew} onClose={() => setShowNew(false)} title="Nouvelle slide">
        <div className="space-y-3">
          <Input value={newTitle} onChange={setNewTitle} placeholder="Titre" className="w-full" />
          <select
            value={newType}
            onChange={(e) => setNewType(e.target.value as SlideType)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg"
          >
            {Object.entries(SLIDE_TYPE_LABELS).map(([k, label]) => (
              <option key={k} value={k}>{label} ({k})</option>
            ))}
          </select>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <Button variant="ghost" onClick={() => setShowNew(false)}>Annuler</Button>
          <Button onClick={createSlide} disabled={!newTitle.trim()}>Créer</Button>
        </div>
      </Modal>
    </div>
  )
}
