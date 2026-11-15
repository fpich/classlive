// Page de connexion formateur.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api/client'
import { useTrainerAuth } from '@/store'
import { Button, Input, Spinner } from '@/components/UI'

export default function LoginPage() {
  const [username, setUsername] = useState('formateur')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const login = useTrainerAuth((s) => s.login)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    try {
      const res = await api.login({ username, password })
      login(res.access_token, username)
      navigate('/home')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur de connexion')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="bg-white p-8 rounded-2xl shadow-lg w-full max-w-sm">
        <div className="text-center mb-6">
          <h1 className="text-3xl font-bold text-brand-600">ClassLive</h1>
          <p className="text-gray-500 mt-1">Connexion formateur</p>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Identifiant</label>
            <Input value={username} onChange={setUsername} placeholder="formateur" className="w-full" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Mot de passe</label>
            <Input type="password" value={password} onChange={setPassword} placeholder="••••••••" className="w-full" />
          </div>
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <Button type="submit" disabled={loading || !password} className="w-full">
            {loading ? <Spinner size="sm" /> : 'Se connecter'}
          </Button>
        </form>
        <div className="mt-6 text-center">
          <button
            onClick={() => navigate('/join')}
            className="text-brand-600 hover:text-brand-700 text-sm"
          >
            Rejoindre un Live étudiant →
          </button>
        </div>
      </div>
    </div>
  )
}
