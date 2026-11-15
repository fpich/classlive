// Point d'entrée de l'application : routes et layout.
// En dev (base '/'), basename = '/'. En prod (base '/app/'), basename = '/app'.
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LoginPage from '@/pages/Login'
import HomePage from '@/pages/Home'
import EditorPage from '@/pages/Editor'
import LiveSetupPage from '@/pages/LiveSetup'
import LiveControlPage from '@/pages/LiveControl'
import ActiveLivesPage from '@/pages/ActiveLives'
import JoinPage from '@/pages/Join'
import StudentLivePage from '@/pages/StudentLive'

const BASENAME = import.meta.env.BASE_URL.replace(/\/$/, '') || '/'

export default function App() {
  return (
    <BrowserRouter basename={BASENAME}>
      <Routes>
        <Route path="/" element={<Navigate to="/home" replace />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/home" element={<HomePage />} />
        <Route path="/editor/:group/:event" element={<EditorPage />} />
        <Route path="/live/:group/:event" element={<LiveSetupPage />} />
        <Route path="/live-control/:liveId" element={<LiveControlPage />} />
        <Route path="/lives" element={<ActiveLivesPage />} />
        <Route path="/join" element={<JoinPage />} />
        <Route path="/join/live" element={<StudentLivePage />} />
        <Route path="*" element={<Navigate to="/home" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
