// Page de jonction étudiant : code à 6 chiffres pré-rempli depuis l'URL, design accueillant.
import { useState, useEffect } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '@/api/client'
import { useStudentSession, useStudentLive } from '@/store'
import { Button, Input, Spinner } from '@/components/UI'

export default function JoinPage() {
  const [searchParams] = useSearchParams()
  const [code, setCode] = useState(searchParams.get('code') || '')
  const [nom, setNom] = useState('')
  const [prenom, setPrenom] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const setSession = useStudentSession((s) => s.setSession)
  const session = useStudentSession((s) => s.token)
  const connectWS = useStudentLive((s) => s.connect)

  useEffect(() => {
    const c = searchParams.get('code')
    if (c && c.length === 6) setCode(c)
  }, [searchParams])

  // Si déjà connecté avec un token valide, proposer d'aller directement au Live
  useEffect(() => {
    if (session) {
      api.studentCurrent(session).then(() => {
        navigate('/join/live')
      }).catch(() => {
        // Token invalide : on le nettoie pour permettre un nouveau join
        useStudentSession.getState().clear()
      })
    }
  }, [session])

  const handleJoin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await api.studentJoin({ session_code: code, nom: nom.trim(), prenom: prenom.trim() })
      setSession({
        token: res.student_session_id,
        participationId: res.participation_id,
        liveId: res.live_id,
        nom: res.nom,
        prenom: res.prenom,
        mode: res.mode,
      })
      connectWS(res.student_session_id)
      navigate('/join/live')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur de connexion')
    } finally {
      setLoading(false)
    }
  }

  // Saisie du code en 6 blocs visuels
  const codeBlocks = code.padEnd(6, ' ').split('')

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-brand-600 to-brand-900 p-4">
      <div className="bg-white p-8 rounded-2xl shadow-2xl w-full max-w-md">
        <div className="text-center mb-6">
          <h1 className="text-4xl font-bold text-brand-600">ClassLive</h1>
          <p className="text-gray-500 mt-2">Rejoignez la session en direct</p>
        </div>

        <form onSubmit={handleJoin} className="space-y-5">
          {/* Code du Live en grand */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2 text-center">Code du Live</label>
            <div className="flex justify-center gap-2 mb-1">
              {codeBlocks.map((c, i) => (
                <div
                  key={i}
                  className={`w-12 h-14 flex items-center justify-center text-2xl font-mono font-bold rounded-lg border-2 ${
                    c !== ' ' ? 'border-brand-500 bg-brand-50 text-brand-700' : 'border-gray-200 bg-gray-50 text-gray-300'
                  }`}
                >
                  {c !== ' ' ? c : '·'}
                </div>
              ))}
            </div>
            <input
              type="text"
              inputMode="numeric"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
              placeholder="000000"
              maxLength={6}
              className="w-full text-center text-lg font-mono tracking-[0.5em] px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-brand-500"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Nom</label>
              <Input value={nom} onChange={setNom} placeholder="Dupont" className="w-full" maxLength={100} />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Prénom</label>
              <Input value={prenom} onChange={setPrenom} placeholder="Marie" className="w-full" maxLength={100} />
            </div>
          </div>

          {error && (
            <div className="p-3 bg-red-50 text-red-700 rounded-lg text-sm text-center">{error}</div>
          )}

          <Button
            type="submit"
            disabled={loading || code.length !== 6 || !nom.trim() || !prenom.trim()}
            className="w-full !py-3 !text-lg"
          >
            {loading ? <Spinner size="sm" /> : 'Rejoindre la session →'}
          </Button>
        </form>

        <p className="text-center text-xs text-gray-400 mt-4">
          Scannez le QR code affiché par le formateur ou entrez le code à 6 chiffres.
        </p>
      </div>
    </div>
  )
}
