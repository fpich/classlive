// Pilotage du Live en direct par le formateur.
// Panneau latéral permanent : code en grand + QR code + lien de jonction copiable.
import { useEffect, useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { api } from '@/api/client'
import { useTrainerAuth, useLiveMonitor } from '@/store'
import { Button, Card, Badge, Spinner, Input } from '@/components/UI'
import Markdown from '@/components/Markdown'
import { ExerciseInput } from '@/components/ExerciseInput'
import { StatsBars } from '@/components/Stats'
import { isExercise, type LiveState, type StudentsResponse, type StatsResponse, type QuestionsResponse, type ReactionsResponse } from '@/types/api'
import { usePublicUrl, buildJoinUrl } from '@/hooks/usePublicUrl'

export default function LiveControlPage() {
  const { liveId = '' } = useParams()
  const navigate = useNavigate()
  const token = useTrainerAuth((s) => s.token)
  const { connect, disconnect } = useLiveMonitor()
  const publicUrl = usePublicUrl()

  const [state, setState] = useState<LiveState | null>(null)
  const [code, setCode] = useState('')
  const [students, setStudents] = useState<StudentsResponse | null>(null)
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [questions, setQuestions] = useState<QuestionsResponse | null>(null)
  const [reactions, setReactions] = useState<ReactionsResponse | null>(null)
  const [activeTab, setActiveTab] = useState<'slide' | 'stats' | 'students' | 'qa'>('slide')
  const [announceText, setAnnounceText] = useState('')
  const [answeringQ, setAnsweringQ] = useState<number | null>(null)
  const [answerText, setAnswerText] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  // Le QR code et le lien pointent TOUJOURS sur l'IP LAN (jamais localhost).
  // Tant que l'IP n'est pas détectée, on utilise window.location.origin comme fallback.
  const joinUrl = buildJoinUrl(code, publicUrl)
  const displayUrl = joinUrl

  const refresh = useCallback(async () => {
    try {
      const [s, st, sts, q, r, active] = await Promise.all([
        api.liveStatus(liveId),
        api.liveStudents(liveId),
        api.liveStats(liveId),
        api.liveQuestions(liveId),
        api.liveReactions(liveId),
        api.activeLives(),
      ])
      setState(s)
      setStudents(st)
      setStats(sts as StatsResponse)
      setQuestions(q)
      setReactions(r)
      const mine = active.lives.find((l) => l.id === liveId)
      if (mine) setCode(mine.code)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    }
  }, [liveId])

  useEffect(() => {
    if (!token) { navigate('/login'); return }
    refresh()
    connect(liveId, token)
    const interval = setInterval(refresh, 5000)
    return () => { clearInterval(interval); disconnect() }
  }, [liveId, token])

  const nav = async (fn: () => Promise<LiveState>) => {
    try { setState(await fn()) } catch (err) { setError(err instanceof Error ? err.message : 'Erreur') }
  }

  const handleStop = async () => {
    if (!confirm('Terminer ce Live ?')) return
    try { await api.liveStop(liveId); navigate('/home') } catch (err) { setError(err instanceof Error ? err.message : 'Erreur') }
  }

  const handleAnnounce = async () => {
    if (!announceText.trim()) return
    try { await api.announce(liveId, announceText.trim()); setAnnounceText('') } catch (err) { setError(err instanceof Error ? err.message : 'Erreur') }
  }

  const handleOrientation = async (orientation: 'paysage' | 'portrait') => {
    try { setState(await api.setOrientation(liveId, orientation)) } catch (err) { setError(err instanceof Error ? err.message : 'Erreur') }
  }

  const handleAnswer = async (qid: number) => {
    if (!answerText.trim()) return
    try {
      await api.answerQuestion(liveId, qid, answerText.trim())
      setAnsweringQ(null); setAnswerText(''); refresh()
    } catch (err) { setError(err instanceof Error ? err.message : 'Erreur') }
  }

  const copyCode = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const copyLink = () => {
    // Copie toujours l'URL réseau (LAN) si détectée
    navigator.clipboard.writeText(displayUrl)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  if (!state) return <div className="min-h-screen flex items-center justify-center"><Spinner size="lg" /></div>

  const currentType = state.slide_type
  const isEx = isExercise(currentType)

  return (
    <div className="min-h-screen bg-gray-900 flex flex-col">
      {/* Header */}
      <header className="bg-gray-800 border-b border-gray-700 px-4 py-2 flex items-center gap-4 flex-wrap">
        <h1 className="font-bold text-brand-400">ClassLive</h1>
        <Badge color="green">EN DIRECT</Badge>
        <span className="text-sm text-gray-400">{state.group} / {state.event}</span>
        <div className="flex-1" />
        <div className="flex gap-1">
          {(['slide', 'stats', 'students', 'qa'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setActiveTab(t)}
              className={`px-3 py-1 rounded-lg text-sm font-medium ${activeTab === t ? 'bg-brand-600 text-white' : 'text-gray-300 hover:bg-gray-700'}`}
            >
              {t === 'slide' ? 'Slide' : t === 'stats' ? `Stats (${stats?.answered ?? 0}/${stats?.total_students ?? 0})` : t === 'students' ? `Élèves (${students?.connected ?? 0}/${students?.total_students ?? 0})` : `Q&A (${questions?.questions.filter((q) => !q.answered).length ?? 0})`}
            </button>
          ))}
        </div>
        <Button variant="danger" size="sm" onClick={handleStop}>Terminer</Button>
      </header>

      {error && <div className="mx-4 mt-2 p-2 bg-red-900/50 text-red-300 rounded text-sm flex justify-between">{error}<button onClick={() => setError('')}>&times;</button></div>}

      <div className="flex-1 flex overflow-hidden">
        {/* Zone principale (projectable) */}
        <div className="flex-1 overflow-hidden p-6 bg-gray-900">
          {activeTab === 'slide' && (
            <div className={`h-full flex flex-col ${state.orientation === 'portrait' ? 'slide-portrait' : ''} live-slide-full`}>
              <div className="flex items-center justify-between mb-4 shrink-0">
                <div className="flex items-center gap-2">
                  <Badge color={isEx ? 'blue' : 'gray'}>{currentType}</Badge>
                  <span className="font-medium">{state.slide}</span>
                </div>
                <span className="text-sm text-gray-400">Slide {state.position}/{state.total}</span>
              </div>
              <div className="slide-content flex-1 min-h-0">
                {isEx ? (
                  <ExerciseInput
                    type={currentType as never}
                    answer={{}}
                    onChange={() => {}}
                    disabled
                    content={state.content || ''}
                  />
                ) : (
                  <Markdown content={state.content || ''} />
                )}
              </div>
              {state.correction_visible && state.correction !== undefined && (
                <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg shrink-0">
                  <strong className="text-green-800">Corrigé :</strong>
                  <pre className="mt-1 text-sm text-green-700 whitespace-pre-wrap">{JSON.stringify(state.correction, null, 2)}</pre>
                </div>
              )}
            </div>
          )}

          {activeTab === 'stats' && stats && (
            <div className="h-full overflow-y-auto">
            <Card className="max-w-2xl mx-auto">
              <h2 className="font-semibold mb-4 text-lg">Réponses — {stats.slide} ({stats.answered}/{stats.total_students})</h2>
              <StatsBars stats={stats} />
            </Card>
            </div>
          )}

          {activeTab === 'students' && students && (
            <div className="h-full overflow-y-auto">
            <Card className="max-w-2xl mx-auto">
              <div className="flex items-center gap-4 mb-4">
                <span>Total : <strong>{students.total_students}</strong></span>
                <Badge color="green">En ligne : {students.connected}</Badge>
                <Badge color="gray">Hors ligne : {students.disconnected}</Badge>
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-gray-500 border-b">
                    <th className="py-2">Nom</th><th className="py-2">Prénom</th>
                    <th className="py-2">Statut</th><th className="py-2">Réponses</th><th className="py-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {students.students.map((s) => (
                    <tr key={s.participation_id} className="border-b border-gray-50">
                      <td className="py-2">{s.nom}</td>
                      <td className="py-2">{s.prenom}</td>
                      <td className="py-2"><Badge color={s.status === 'connected' ? 'green' : 'gray'}>{s.status}</Badge></td>
                      <td className="py-2">{s.answered}</td>
                      <td className="py-2">
                        <button onClick={async () => {
                          if (!confirm(`Exclure ${s.prenom} ${s.nom} ?`)) return
                          try { await api.kickStudent(liveId, s.participation_id); refresh() } catch (err) { setError(err instanceof Error ? err.message : 'Erreur') }
                        }} className="text-red-400 hover:text-red-600 text-xs">Exclure</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
            </div>
          )}

          {activeTab === 'qa' && questions && (
            <div className="h-full overflow-y-auto">
            <Card className="max-w-2xl mx-auto">
              <h2 className="font-semibold mb-4">Questions ({questions.questions.length})</h2>
              {questions.questions.length === 0 ? <p className="text-gray-400 text-sm">Aucune question</p> : (
                <div className="space-y-3">
                  {questions.questions.map((q) => (
                    <div key={q.id} className={`p-3 rounded-lg border ${q.answered ? 'border-green-200 bg-green-50' : 'border-gray-200'}`}>
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-sm">{q.prenom} {q.nom}</span>
                        <span className="text-xs text-gray-400">{q.asked_at}</span>
                        {q.answered && <Badge color="green">répondu</Badge>}
                      </div>
                      <p className="text-sm mb-2">{q.text}</p>
                      {q.answered && q.answer_text && <p className="text-sm text-green-700">→ {q.answer_text}</p>}
                      {!q.answered && answeringQ !== q.id && (
                        <Button size="sm" variant="secondary" onClick={() => { setAnsweringQ(q.id); setAnswerText('') }}>Répondre</Button>
                      )}
                      {answeringQ === q.id && (
                        <div className="flex gap-2 mt-2">
                          <Input value={answerText} onChange={setAnswerText} placeholder="Votre réponse..." className="flex-1" maxLength={1000} />
                          <Button size="sm" onClick={() => handleAnswer(q.id)} disabled={!answerText.trim()}>Envoyer</Button>
                          <Button size="sm" variant="ghost" onClick={() => setAnsweringQ(null)}>Annuler</Button>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>
            </div>
          )}
        </div>

        {/* ── Panneau latéral permanent : code + QR + contrôles ── */}
        <div className="w-80 bg-gray-800 border-l border-gray-700 flex flex-col overflow-y-auto">
          {/* Code en grand */}
          <div className="p-4 text-center border-b border-gray-700">
            <p className="text-gray-400 text-xs uppercase tracking-wide mb-2">Code du Live</p>
            <button onClick={copyCode} className="block w-full">
              <span className="font-mono font-bold text-5xl text-white tracking-widest hover:text-brand-400 transition-colors cursor-pointer">
                {code ? code.split('').join(' ') : '------'}
              </span>
            </button>
            <button onClick={copyCode} className="mt-2 text-xs text-brand-400 hover:underline">
              {copied ? 'Copié !' : 'Cliquer pour copier le code'}
            </button>
          </div>

          {/* QR code — pointe sur l'URL publique configurée (expose.conf) */}
          {code && (
            <div className="p-4 text-center border-b border-gray-700">
              <div className="bg-white p-3 rounded-xl inline-block">
                <QRCodeSVG value={joinUrl} size={160} level="M" />
              </div>
              <p className="text-xs text-green-400 mt-2 break-all font-medium">
                {displayUrl}
              </p>
              <button onClick={copyLink} className="mt-2 text-xs text-brand-400 hover:underline">
                Copier le lien de jonction
              </button>
            </div>
          )}

          {/* Contrôles de navigation */}
          <div className="p-4 space-y-2 border-b border-gray-700">
            <p className="text-gray-400 text-xs uppercase tracking-wide mb-2">Navigation</p>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => nav(() => api.livePrevious(liveId))} disabled={state.position <= 1} className="flex-1">
                &larr; Préc.
              </Button>
              <span className="text-white text-sm self-center">{state.position}/{state.total}</span>
              <Button size="sm" onClick={() => nav(() => api.liveNext(liveId))} disabled={state.position >= state.total} className="flex-1">
                Suiv. &rarr;
              </Button>
            </div>
            {isEx && !state.correction_visible && (
              <Button size="sm" variant="secondary" onClick={() => nav(() => api.showCorrection(liveId))} className="w-full">
                Afficher le corrigé
              </Button>
            )}
            {isEx && state.correction_visible && (
              <Button size="sm" variant="secondary" onClick={() => nav(() => api.hideCorrection(liveId))} className="w-full">
                Masquer le corrigé
              </Button>
            )}
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => handleOrientation('paysage')} className={`flex-1 ${state.orientation === 'paysage' ? '!bg-brand-600 !text-white' : ''}`}>
                Paysage
              </Button>
              <Button size="sm" variant="secondary" onClick={() => handleOrientation('portrait')} className={`flex-1 ${state.orientation === 'portrait' ? '!bg-brand-600 !text-white' : ''}`}>
                Portrait
              </Button>
            </div>
            <div className="flex gap-2">
              <Input value={announceText} onChange={setAnnounceText} placeholder="Annonce..." className="flex-1 !bg-gray-700 !border-gray-600 !text-white text-sm" maxLength={500} />
              <Button size="sm" onClick={handleAnnounce} disabled={!announceText.trim()}>OK</Button>
            </div>
          </div>

          {/* Réactions */}
          {reactions && Object.keys(reactions.counts).length > 0 && (
            <div className="p-4 border-b border-gray-700">
              <p className="text-gray-400 text-xs uppercase tracking-wide mb-2">Réactions</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(reactions.counts).map(([emoji, n]) => (
                  <span key={emoji} className="text-2xl">{emoji}<span className="text-xs text-gray-400 ml-0.5">{n}</span></span>
                ))}
              </div>
            </div>
          )}

          {/* Annonce active */}
          {state.announcement && (
            <div className="p-4">
              <p className="text-gray-400 text-xs uppercase tracking-wide mb-1">Annonce</p>
              <p className="text-yellow-300 text-sm">{state.announcement}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
