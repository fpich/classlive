// Store global Zustand : authentification formateur + session étudiant.
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { setToken } from '@/api/client'
import type { StudentState, LiveState, StudentsResponse, StatsResponse, QuestionsResponse, ReactionsResponse, WSEvent } from '@/types/api'
import { ClassLiveWS } from '@/api/ws'

interface TrainerAuth {
  token: string | null
  username: string | null
  login: (token: string, username: string) => void
  logout: () => void
  isAuthenticated: () => boolean
}

interface StudentSession {
  token: string | null
  participationId: string | null
  liveId: string | null
  nom: string | null
  prenom: string | null
  mode: string | null
  setSession: (data: { token: string; participationId: string; liveId: string; nom: string; prenom: string; mode: string }) => void
  clear: () => void
}

interface LiveMonitor {
  ws: ClassLiveWS | null
  current: LiveState | null
  students: StudentsResponse | null
  stats: StatsResponse | null
  questions: QuestionsResponse | null
  reactions: ReactionsResponse | null
  connect: (liveId: string, token: string) => void
  disconnect: () => void
  handleEvent: (event: WSEvent) => void
}

interface StudentLive {
  ws: ClassLiveWS | null
  current: StudentState | null
  connect: (token: string) => void
  disconnect: () => void
  handleEvent: (event: WSEvent) => void
}

export const useTrainerAuth = create<TrainerAuth>()(
  persist(
    (set, get) => ({
      token: null,
      username: null,
      login: (token, username) => {
        setToken(token)
        set({ token, username })
      },
      logout: () => {
        setToken(null)
        set({ token: null, username: null })
      },
      isAuthenticated: () => !!get().token,
    }),
    { name: 'classlive-trainer' }
  )
)

export const useStudentSession = create<StudentSession>()(
  persist(
    (set) => ({
      token: null,
      participationId: null,
      liveId: null,
      nom: null,
      prenom: null,
      mode: null,
      setSession: (data) => set({ ...data }),
      clear: () => set({ token: null, participationId: null, liveId: null, nom: null, prenom: null, mode: null }),
    }),
    { name: 'classlive-student' }
  )
)

export const useLiveMonitor = create<LiveMonitor>((set, get) => ({
  ws: null,
  current: null,
  students: null,
  stats: null,
  questions: null,
  reactions: null,
  connect: (liveId, token) => {
    get().disconnect()
    const ws = new ClassLiveWS(token, `/live/${liveId}/monitor`)
    ws.onMessage((event) => get().handleEvent(event))
    ws.connect()
    set({ ws })
  },
  disconnect: () => {
    get().ws?.close()
    set({ ws: null, current: null, students: null, stats: null, questions: null, reactions: null })
  },
  handleEvent: (event) => {
    switch (event.event) {
      case 'monitor':
        set({ current: event.current, students: event.students })
        break
      case 'slide_changed':
        set({ current: event.current as LiveState })
        break
      case 'correction_shown':
      case 'correction_hidden':
        set({ current: event.current as LiveState })
        break
      case 'student_joined':
      case 'student_connected':
      case 'student_disconnected':
      case 'student_kicked':
      case 'answer_received':
      case 'student_finished':
        // Rafraîchira students/stats via polling ou re-fetch
        break
      case 'question_asked':
      case 'question_updated':
        break
      case 'live_ended':
        break
    }
  },
}))

export const useStudentLive = create<StudentLive>((set, get) => ({
  ws: null,
  current: null,
  connect: (token) => {
    get().disconnect()
    const ws = new ClassLiveWS(token, '/student/ws')
    ws.onMessage((event) => get().handleEvent(event))
    ws.connect()
    set({ ws })
  },
  disconnect: () => {
    get().ws?.close()
    set({ ws: null, current: null })
  },
  handleEvent: (event) => {
    switch (event.event) {
      case 'current':
      case 'slide_changed':
        set({ current: event.current as StudentState })
        break
      case 'correction_shown':
      case 'correction_hidden':
        set({ current: event.current as unknown as StudentState })
        break
      case 'orientation_changed':
        set({ current: event.current as unknown as StudentState })
        break
      case 'live_ended':
      case 'session_ended':
        set({ current: { ...get().current!, status: 'ended' } })
        break
      case 'answer_locked':
        if (get().current) set({ current: { ...get().current!, locked: true } })
        break
    }
  },
}))
