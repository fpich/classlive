// Interface étudiant pendant le Live : slide courante, réponse, navigation autonome, Q&A, réactions.
import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { useStudentSession, useStudentLive } from '@/store'
import { Button, Card, Input, Spinner, Badge } from '@/components/UI'
import Markdown from '@/components/Markdown'
import { ExerciseInput, exerciseTypeLabel } from '@/components/ExerciseInput'
import { isExercise } from '@/types/api'

const EMOJIS = ['👍', '👎', '❤️', '😂', '😮', '🎉', '🤔', '👏']

export default function StudentLivePage() {
  const navigate = useNavigate()
  const session = useStudentSession()
  const { current, connect, disconnect } = useStudentLive()
  const [answer, setAnswer] = useState<Record<string, unknown>>({})
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [questionText, setQuestionText] = useState('')
  const [myQuestions, setMyQuestions] = useState<{ id: number; text: string; answered: boolean; answer_text: string | null }[]>([])
  const [showQA, setShowQA] = useState(false)

  const refresh = useCallback(async () => {
    if (!session.token) return
    try {
      const cur = await api.studentCurrent(session.token)
      // Mise à jour via le store serait mieux, mais on force ici
      useStudentLive.setState({ current: cur })
      setSubmitted(cur.locked || false)
      const qs = await api.studentQuestions(session.token)
      setMyQuestions(qs.questions.map((q) => ({ id: q.id, text: q.text, answered: q.answered, answer_text: q.answer_text })))
    } catch (err) {
      // Ne déconnecter que si le token est vraiment invalide (401) ou session terminée
      if (err instanceof Error && (err.message.includes('401') || err.message.includes('Jeton'))) {
        session.clear()
        navigate('/join')
      }
      // sinon (erreur réseau temporaire) : on garde la session, le prochain poll retentera
    }
  }, [session.token])

  useEffect(() => {
    if (!session.token) { navigate('/join'); return }
    connect(session.token)
    refresh()
    const interval = setInterval(refresh, 10000)
    return () => { clearInterval(interval); disconnect() }
  }, [session.token])

  // Reset answer quand la slide change
  useEffect(() => {
    setAnswer({})
    setSubmitted(current?.locked || false)
  }, [current?.slide, current?.number])

  const handleSubmit = async () => {
    if (!session.token || Object.keys(answer).length === 0) return
    try {
      setSubmitting(true)
      setError('')
      const res = await api.studentAnswer(session.token, answer)
      setSubmitted(true)
      if (res.locked) refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    } finally {
      setSubmitting(false)
    }
  }

  const handleNext = async () => {
    if (!session.token) return
    try { await api.studentNext(session.token); refresh() } catch (err) { setError(err instanceof Error ? err.message : 'Erreur') }
  }

  const handlePrevious = async () => {
    if (!session.token) return
    try { await api.studentPrevious(session.token); refresh() } catch (err) { setError(err instanceof Error ? err.message : 'Erreur') }
  }

  const handleAsk = async () => {
    if (!session.token || !questionText.trim()) return
    try { await api.studentAsk(session.token, questionText.trim()); setQuestionText(''); refresh() } catch (err) { setError(err instanceof Error ? err.message : 'Erreur') }
  }

  const handleReaction = async (emoji: string) => {
    if (!session.token) return
    try { await api.studentReaction(session.token, emoji) } catch {}
  }

  if (!current) {
    return <div className="min-h-screen flex items-center justify-center"><Spinner size="lg" /></div>
  }

  if (current.status === 'ended') {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <Card className="text-center p-8">
          <h1 className="text-2xl font-bold text-gray-800 mb-2">Session terminée</h1>
          <p className="text-gray-500 mb-4">Le formateur a arrêté ce Live.</p>
          <Button onClick={() => { session.clear(); navigate('/join') }}>Retour</Button>
        </Card>
      </div>
    )
  }

  const isEx = isExercise(current.slide_type)
  const isAutonome = current.mode === 'autonome'
  const showCorrection = current.correction !== undefined && (current.correction_visible || (isAutonome && current.correction !== undefined))

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 px-4 py-3 flex items-center gap-3 flex-wrap sticky top-0 z-10">
        <h1 className="font-bold text-brand-600">ClassLive</h1>
        <span className="text-sm text-gray-600">{session.prenom} {session.nom}</span>
        <Badge color="blue">{current.online} en ligne</Badge>
        <div className="flex-1" />
        {current.announcement && (
          <span className="text-sm bg-yellow-100 text-yellow-800 px-2 py-1 rounded">📢 {current.announcement}</span>
        )}
        <div className="flex gap-1">
          {EMOJIS.map((e) => (
            <button key={e} onClick={() => handleReaction(e)} className="text-xl hover:scale-125 transition-transform">{e}</button>
          ))}
        </div>
      </header>

      {error && <div className="mx-4 mt-2 p-2 bg-red-50 text-red-700 rounded text-sm flex justify-between">{error}<button onClick={() => setError('')}>&times;</button></div>}

      <main className="max-w-3xl mx-auto p-4">
        {/* Progression */}
        <div className="flex items-center gap-2 mb-4 text-sm text-gray-500">
          <span>Slide {current.position}/{current.total}</span>
          <div className="flex-1 bg-gray-200 rounded-full h-2">
            <div className="bg-brand-500 h-full rounded-full transition-all" style={{ width: `${(current.position / current.total) * 100}%` }} />
          </div>
          {isAutonome && current.finished && <Badge color="green">Terminé</Badge>}
        </div>

        {/* Slide */}
        <Card className="mb-4">
          <div className="flex items-center gap-2 mb-3">
            <Badge color={isEx ? 'blue' : 'gray'}>{exerciseTypeLabel(current.slide_type)}</Badge>
            <span className="font-medium">{current.slide}</span>
            {current.expires_at && !current.time_expired && (
              <Countdown expiresAt={current.expires_at} />
            )}
            {current.time_expired && <Badge color="red">Temps écoulé</Badge>}
          </div>
          <div className={`slide-landscape ${current.orientation === 'portrait' ? 'slide-portrait' : ''}`}>
            <Markdown content={current.content} />
          </div>

          {/* Correction */}
          {showCorrection && current.correction !== undefined && (
            <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
              <strong className="text-green-800">Corrigé :</strong>
              <pre className="mt-1 text-sm text-green-700 whitespace-pre-wrap">{JSON.stringify(current.correction, null, 2)}</pre>
            </div>
          )}
        </Card>

        {/* Exercice */}
        {isEx && !current.finished && (
          <Card className="mb-4">
            <h3 className="font-medium mb-3">Votre réponse</h3>
            <ExerciseInput
              type={current.slide_type as never}
              answer={answer}
              onChange={setAnswer}
              disabled={submitted || current.locked || current.time_expired}
              content={current.content}
            />
            <div className="mt-4 flex gap-2">
              <Button
                onClick={handleSubmit}
                disabled={submitting || submitted || !isAnswerComplete(current.slide_type, answer, current.content)}
              >
                {submitting ? <Spinner size="sm" /> : submitted ? 'Réponse envoyée' : 'Valider ma réponse'}
              </Button>
              {submitted && <Badge color="green">Verrouillée</Badge>}
            </div>
          </Card>
        )}

        {/* Navigation autonome */}
        {isAutonome && (
          <div className="flex gap-2 mb-4">
            <Button variant="secondary" onClick={handlePrevious} disabled={current.position <= 1}>&larr; Précédent</Button>
            <Button onClick={handleNext} disabled={current.finished || (isEx && !submitted && !current.locked)}>
              Suivant &rarr;
            </Button>
          </div>
        )}

        {/* Q&A */}
        <Card>
          <button onClick={() => setShowQA(!showQA)} className="flex items-center justify-between w-full text-left">
            <span className="font-medium">Questions ({myQuestions.length})</span>
            <span>{showQA ? '▲' : '▼'}</span>
          </button>
          {showQA && (
            <div className="mt-3 space-y-2">
              <div className="flex gap-2">
                <Input value={questionText} onChange={setQuestionText} placeholder="Poser une question..." className="flex-1" maxLength={1000} />
                <Button size="sm" onClick={handleAsk} disabled={!questionText.trim()}>Envoyer</Button>
              </div>
              {myQuestions.map((q) => (
                <div key={q.id} className={`p-2 rounded text-sm ${q.answered ? 'bg-green-50' : 'bg-gray-50'}`}>
                  <p>{q.text}</p>
                  {q.answered && q.answer_text && <p className="text-green-700 text-xs mt-1">→ {q.answer_text}</p>}
                </div>
              ))}
            </div>
          )}
        </Card>
      </main>
    </div>
  )
}

function Countdown({ expiresAt }: { expiresAt: string }) {
  const [left, setLeft] = useState('')
  useEffect(() => {
    const update = () => {
      const diff = new Date(expiresAt).getTime() - Date.now()
      if (diff <= 0) { setLeft('0s'); return }
      const s = Math.ceil(diff / 1000)
      setLeft(s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`)
    }
    update()
    const i = setInterval(update, 1000)
    return () => clearInterval(i)
  }, [expiresAt])
  return <Badge color="yellow">⏱ {left}</Badge>
}

// Vérifie qu'une réponse est complète avant validation
function isAnswerComplete(type: string, answer: Record<string, unknown>, content?: string): boolean {
  switch (type) {
    case 'T': {
      const nbTrous = content ? (content.match(/_{2,}/g) || []).length : 0
      const blanks = (answer.blanks as string[]) || []
      return blanks.length >= nbTrous && blanks.every((b) => b && b.trim())
    }
    case 'Q':
    case 'P':
      return Array.isArray(answer.selected) && answer.selected.length > 0
    case 'F':
      return typeof answer.text === 'string' && answer.text.trim().length > 0
    case 'N':
      return Array.isArray(answer.words) && answer.words.length > 0
    case 'L':
      return typeof answer.value === 'number'
    case 'I':
      return typeof answer.x === 'number' && typeof answer.y === 'number'
    case 'O': {
      const items = content ? (content.match(/^\s*(?:[-*+]\s+|\d+\.\s+)/gm) || []).length : 0
      const order = (answer.order as string[]) || []
      return order.length >= items && order.every((o) => o && o.trim())
    }
    case 'R': {
      const items = content ? (content.match(/^\s*(?:[-*+]\s+|\d+\.\s+)/gm) || []).length : 0
      const cats = (answer.categories as Record<string, string>) || {}
      return Object.keys(cats).length >= items && Object.values(cats).every((c) => c && c.trim())
    }
    case 'A': {
      const pairs = content ? (content.match(/=>/g) || []).length : 0
      const p = (answer.pairs as Record<string, string>) || {}
      return Object.keys(p).length >= pairs && Object.values(p).every((r) => r && r.trim())
    }
    default:
      return Object.keys(answer).length > 0
  }
}
