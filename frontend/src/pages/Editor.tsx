// Éditeur de slides : liste, création, édition Markdown, médias.
import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { Button, Card, Input, Modal, Spinner, Badge } from '@/components/UI'
import Markdown from '@/components/Markdown'
import { SLIDE_TYPE_LABELS, type SlideType } from '@/types/api'

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

  const createSlide = async () => {
    if (!newTitle.trim()) return
    try {
      const res = await api.createSlide(group, event, { title: newTitle.trim(), slide_type: newType, content: '' })
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
                  <Button size="sm" onClick={saveContent} disabled={saving}>
                    {saving ? <Spinner size="sm" /> : 'Enregistrer'}
                  </Button>
                </div>
              </div>
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
