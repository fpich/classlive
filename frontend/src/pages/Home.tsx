// Page d'accueil formateur : liste des groupes et événements, création.
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { useTrainerAuth } from '@/store'
import { Button, Card, Input, Modal, Spinner, Badge } from '@/components/UI'
import { usePublicUrl, buildJoinUrl } from '@/hooks/usePublicUrl'
import type { EventInfo, ActiveLivesResponse } from '@/types/api'

export default function HomePage() {
  const publicUrl = usePublicUrl()
  const [groups, setGroups] = useState<string[]>([])
  const [events, setEvents] = useState<Record<string, string[]>>({})
  const [allEvents, setAllEvents] = useState<EventInfo[]>([])
  const [activeLives, setActiveLives] = useState<ActiveLivesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showNewGroup, setShowNewGroup] = useState(false)
  const [showNewEvent, setShowNewEvent] = useState<string | null>(null)
  const [newGroupName, setNewGroupName] = useState('')
  const [newEventTitle, setNewEventTitle] = useState('')
  const [copied, setCopied] = useState(false)
  const navigate = useNavigate()
  const logout = useTrainerAuth((s) => s.logout)
  const token = useTrainerAuth((s) => s.token)

  const load = async () => {
    try {
      setLoading(true)
      const [g, e, al] = await Promise.all([api.listGroups(), api.listAllEvents(), api.activeLives()])
      setGroups(g.groups)
      setAllEvents(e.events)
      setActiveLives(al)
      const evts: Record<string, string[]> = {}
      for (const group of g.groups) {
        const res = await api.listEvents(group)
        evts[group] = res.events
      }
      setEvents(evts)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!token) { navigate('/login'); return }
    load()
  }, [token])

  const handleCreateGroup = async () => {
    if (!newGroupName.trim()) return
    try {
      await api.createGroup(newGroupName.trim())
      setNewGroupName('')
      setShowNewGroup(false)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    }
  }

  const handleCreateEvent = async (group: string) => {
    if (!newEventTitle.trim()) return
    try {
      await api.createEvent(group, newEventTitle.trim())
      setNewEventTitle('')
      setShowNewEvent(null)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    }
  }

  const handleDeleteGroup = async (group: string) => {
    if (!confirm(`Supprimer le groupe ${group} et tout son contenu ?`)) return
    try {
      await api.deleteGroup(group)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    }
  }

  const handleDeleteEvent = async (group: string, event: string) => {
    if (!confirm(`Supprimer l'événement ${event} ?`)) return
    try {
      await api.deleteEvent(group, event)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur')
    }
  }

  if (loading && groups.length === 0) {
    return <div className="min-h-screen flex items-center justify-center"><Spinner size="lg" /></div>
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold text-brand-600 cursor-pointer" onClick={() => navigate('/home')}>ClassLive</h1>
        <div className="flex items-center gap-3">
          <button onClick={() => navigate('/lives')} className="text-sm text-brand-600 hover:underline">
            Lives actifs
          </button>
          <Button variant="ghost" size="sm" onClick={() => { logout(); navigate('/login') }}>Déconnexion</Button>
        </div>
      </header>

      <main className="max-w-4xl mx-auto p-6">
        {error && (
          <div className="mb-4 p-3 bg-red-50 text-red-700 rounded-lg text-sm flex justify-between">
            {error}
            <button onClick={() => setError('')}>&times;</button>
          </div>
        )}

        {/* Bandeau Live actif avec code en grand */}
        {activeLives && activeLives.lives.length > 0 && (
          <div className="mb-6 bg-gradient-to-r from-green-600 to-brand-600 rounded-xl p-6 text-white flex items-center gap-6 flex-wrap">
            <div>
              <Badge color="green">EN DIRECT</Badge>
              <p className="text-sm opacity-90 mt-1">
                {activeLives.lives[0].group_name} / {activeLives.lives[0].event_name}
              </p>
            </div>
            <div className="text-center">
              <p className="text-xs uppercase tracking-wide opacity-75">Code à communiquer aux élèves</p>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(activeLives.lives[0].code)
                  setCopied(true)
                  setTimeout(() => setCopied(false), 2000)
                }}
                className="font-mono font-bold text-5xl tracking-[0.3em] hover:opacity-80 transition-opacity cursor-pointer"
                title="Cliquer pour copier"
              >
                {activeLives.lives[0].code}
              </button>
              <p className="text-xs opacity-75 mt-1">{copied ? 'Copié !' : 'cliquer pour copier'}</p>
            </div>
            {/* Lien élève toujours sur l'IP LAN */}
            <div className="text-xs opacity-90">
              <p className="uppercase tracking-wide opacity-75">Lien élèves (réseau)</p>
              <button
                onClick={() => {
                  navigator.clipboard.writeText(buildJoinUrl(activeLives.lives[0].code, publicUrl))
                  setCopied(true)
                  setTimeout(() => setCopied(false), 2000)
                }}
                className="font-mono bg-white/20 px-2 py-1 rounded hover:bg-white/30 break-all"
                title="Copier le lien réseau"
              >
                {buildJoinUrl(activeLives.lives[0].code, publicUrl)}
              </button>
            </div>
            <div className="flex-1" />
            <Button onClick={() => navigate(`/live-control/${activeLives.lives[0].id}`)} className="!bg-white !text-brand-700 hover:!bg-gray-100">
              Ouvrir le pilotage →
            </Button>
          </div>
        )}

        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-gray-800">Groupes</h2>
          <Button onClick={() => setShowNewGroup(true)}>+ Nouveau groupe</Button>
        </div>

        {groups.length === 0 ? (
          <Card className="text-center py-12 text-gray-500">
            Aucun groupe. Créez votre premier groupe pour commencer.
          </Card>
        ) : (
          <div className="space-y-4">
            {groups.map((group) => (
              <Card key={group}>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="font-semibold text-gray-800">{group}</h3>
                  <div className="flex gap-2">
                    <Button size="sm" variant="secondary" onClick={() => setShowNewEvent(group)}>
                      + Événement
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => handleDeleteGroup(group)} className="text-red-600">
                      Supprimer
                    </Button>
                  </div>
                </div>
                <div className="space-y-1">
                  {(events[group] || []).length === 0 ? (
                    <p className="text-sm text-gray-400">Aucun événement</p>
                  ) : (
                    (events[group] || []).map((event) => {
                      const live = activeLives?.lives.find(
                        (l) => l.group_name === group && l.event_name === event
                      )
                      return (
                      <div
                        key={event}
                        className="flex items-center justify-between px-3 py-2 bg-gray-50 rounded-lg hover:bg-gray-100"
                      >
                        <button
                          onClick={() => navigate(`/editor/${encodeURIComponent(group)}/${encodeURIComponent(event)}`)}
                          className="text-brand-600 hover:underline text-left flex-1 flex items-center gap-2"
                        >
                          {event}
                          {live && <Badge color="green">EN DIRECT · {live.code}</Badge>}
                        </button>
                        <div className="flex gap-2">
                          {live ? (
                            <Button size="sm" onClick={() => navigate(`/live-control/${live.id}`)}>
                              Pilotage →
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              variant="secondary"
                              onClick={() => navigate(`/live/${encodeURIComponent(group)}/${encodeURIComponent(event)}`)}
                            >
                              Lancer un Live
                            </Button>
                          )}
                          <button
                            onClick={() => handleDeleteEvent(group, event)}
                            className="text-red-400 hover:text-red-600 text-sm px-2"
                          >
                            &times;
                          </button>
                        </div>
                      </div>
                      )
                    })
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}

        {allEvents.length > 0 && (
          <div className="mt-8">
            <h3 className="text-lg font-medium text-gray-700 mb-3">Tous les événements ({allEvents.length})</h3>
            <div className="flex flex-wrap gap-2">
              {allEvents.map((e) => (
                <Badge key={`${e.group}/${e.title}`} color="blue">
                  {e.group} / {e.title}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </main>

      <Modal open={showNewGroup} onClose={() => setShowNewGroup(false)} title="Nouveau groupe">
        <Input
          value={newGroupName}
          onChange={setNewGroupName}
          placeholder="Nom du groupe (ex: Formation Python)"
          className="w-full mb-4"
          onKeyDown={(e) => { if (e.key === 'Enter') handleCreateGroup() }}
        />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setShowNewGroup(false)}>Annuler</Button>
          <Button onClick={handleCreateGroup} disabled={!newGroupName.trim()}>Créer</Button>
        </div>
      </Modal>

      <Modal open={showNewEvent !== null} onClose={() => setShowNewEvent(null)} title={`Nouvel événement dans ${showNewEvent || ''}`}>
        <Input
          value={newEventTitle}
          onChange={setNewEventTitle}
          placeholder="Titre (ex: Introduction)"
          className="w-full mb-4"
          onKeyDown={(e) => { if (e.key === 'Enter' && showNewEvent) handleCreateEvent(showNewEvent) }}
        />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => setShowNewEvent(null)}>Annuler</Button>
          <Button onClick={() => showNewEvent && handleCreateEvent(showNewEvent)} disabled={!newEventTitle.trim()}>Créer</Button>
        </div>
      </Modal>
    </div>
  )
}
