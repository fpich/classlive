// Configuration et lancement d'un Live par le formateur.
import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { Button, Card, Input, Spinner } from '@/components/UI'
import type { LiveMode, TimingMode } from '@/types/api'

export default function LiveSetupPage() {
  const { group = '', event = '' } = useParams()
  const navigate = useNavigate()
  const [mode, setMode] = useState<LiveMode>('live')
  const [timing, setTiming] = useState<TimingMode>('none')
  const [timingSeconds, setTimingSeconds] = useState('60')
  const [correction, setCorrection] = useState('à_la_fin')
  const [anonymous, setAnonymous] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleStart = async () => {
    try {
      setLoading(true)
      setError('')
      const res = await api.startLive({
        group,
        title: event,
        mode,
        timing,
        timing_seconds: timing !== 'none' ? parseInt(timingSeconds, 10) : undefined,
        correction: mode === 'autonome' ? correction : undefined,
        anonymous,
      })
      navigate(`/live-control/${res.live_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <Card className="w-full max-w-lg">
        <div className="flex items-center gap-3 mb-6">
          <button onClick={() => navigate(-1)} className="text-gray-400 hover:text-gray-600">&larr;</button>
          <div>
            <h1 className="text-xl font-bold text-gray-800">Lancer un Live</h1>
            <p className="text-sm text-gray-500">{group} / {event}</p>
          </div>
        </div>

        {error && <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm">{error}</div>}

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Mode</label>
            <div className="flex gap-2">
              <button
                onClick={() => setMode('live')}
                className={`flex-1 px-4 py-2 rounded-lg border text-sm font-medium ${mode === 'live' ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-700 border-gray-300'}`}
              >
                Live (vous pilotez)
              </button>
              <button
                onClick={() => setMode('autonome')}
                className={`flex-1 px-4 py-2 rounded-lg border text-sm font-medium ${mode === 'autonome' ? 'bg-brand-600 text-white border-brand-600' : 'bg-white text-gray-700 border-gray-300'}`}
              >
                Autonome (rythme perso)
              </button>
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Compte à rebours</label>
            <select
              value={timing}
              onChange={(e) => setTiming(e.target.value as TimingMode)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg"
            >
              <option value="none">Aucun</option>
              <option value="par_question">Par question</option>
              {mode === 'autonome' && <option value="par_evenement">Par événement (durée totale)</option>}
            </select>
          </div>

          {timing !== 'none' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Durée (secondes)</label>
              <Input
                type="number"
                value={timingSeconds}
                onChange={setTimingSeconds}
                className="w-full"
              />
            </div>
          )}

          {mode === 'autonome' && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Correction</label>
              <select
                value={correction}
                onChange={(e) => setCorrection(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg"
              >
                <option value="jamais">Jamais</option>
                <option value="après_question">Après chaque question</option>
                <option value="à_la_fin">À la fin</option>
              </select>
            </div>
          )}

          <label className="flex items-center gap-2 text-sm text-gray-700">
            <input
              type="checkbox"
              checked={anonymous}
              onChange={(e) => setAnonymous(e.target.checked)}
              className="rounded"
            />
            Mode anonyme (masquer les identités dans les résultats)
          </label>

          <Button onClick={handleStart} disabled={loading} className="w-full" size="lg">
            {loading ? <Spinner size="sm" /> : 'Démarrer le Live'}
          </Button>
        </div>
      </Card>
    </div>
  )
}
