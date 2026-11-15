// Liste des Lives actifs (pour retrouver une session après refresh).
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { useTrainerAuth } from '@/store'
import { Button, Card, Spinner, Badge } from '@/components/UI'
import type { ActiveLivesResponse } from '@/types/api'

export default function ActiveLivesPage() {
  const [data, setData] = useState<ActiveLivesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const navigate = useNavigate()
  const token = useTrainerAuth((s) => s.token)

  useEffect(() => {
    if (!token) { navigate('/login'); return }
    api.activeLives().then(setData).catch(() => {}).finally(() => setLoading(false))
  }, [token])

  if (loading) return <div className="min-h-screen flex items-center justify-center"><Spinner size="lg" /></div>

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-brand-600 cursor-pointer" onClick={() => navigate('/home')}>ClassLive</h1>
        <Button variant="ghost" size="sm" onClick={() => navigate('/home')}>&larr; Retour</Button>
      </header>
      <main className="max-w-3xl mx-auto p-6">
        <h2 className="text-xl font-semibold mb-4">Lives en cours ({data?.lives.length ?? 0})</h2>
        {!data || data.lives.length === 0 ? (
          <Card className="text-center py-8 text-gray-500">Aucun Live actif pour le moment.</Card>
        ) : (
          <div className="space-y-3">
            {data.lives.map((l) => (
              <Card key={l.id}>
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-medium">{l.group_name} / {l.event_name}</div>
                    <div className="text-sm text-gray-500">
                      Code <span className="font-mono font-bold">{l.code}</span> · {l.mode} · démarré le {l.started_at}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge color="green">actif</Badge>
                    <Button size="sm" onClick={() => navigate(`/live-control/${l.id}`)}>
                      Reprendre
                    </Button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
