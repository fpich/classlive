// Client HTTP pour l'API ClassLive. Gère le Bearer token et les erreurs.
import type {
  LoginRequest, LoginResponse, GroupResult, EventResult, EventInfo,
  SlideRequest, SlideInfo, SlideContent, StartLiveRequest, StartLiveResponse,
  LiveState, StudentState, JoinRequest, JoinResponse,
  SubmitAnswerResponse, StudentsResponse, ResultsResponse, StatsResponse,
  AllStatsResponse, QuestionsResponse, ReactionsResponse, SessionsResponse,
  ActiveLivesResponse,
} from '@/types/api'

const BASE = '/api/v1'

class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let token: string | null = localStorage.getItem('classlive_token')

export function setToken(t: string | null) {
  token = t
  if (t) localStorage.setItem('classlive_token', t)
  else localStorage.removeItem('classlive_token')
}

export function getToken(): string | null {
  return token
}

async function req<T>(path: string, options: RequestInit = {}, auth = true): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  }
  if (auth && token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${BASE}${path}`, { ...options, headers })
  if (res.status === 204) return undefined as T
  const body = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError(res.status, body.detail || `Erreur ${res.status}`)
  return body as T
}

// ── Auth ──────────────────────────────────────────────────────────────────

export const api = {
  login: (data: LoginRequest) =>
    req<LoginResponse>('/auth/login', { method: 'POST', body: JSON.stringify(data) }, false),

  // ── Groupes ────────────────────────────────────────────────────────────

  listGroups: () => req<{ groups: string[] }>('/groups'),
  createGroup: (group: string) =>
    req<GroupResult>('/groups', { method: 'POST', body: JSON.stringify({ group }) }),
  deleteGroup: (group: string) =>
    req<GroupResult>(`/groups/${encodeURIComponent(group)}`, { method: 'DELETE' }),
  duplicateGroup: (group: string, new_title?: string) =>
    req<GroupResult>(`/groups/${encodeURIComponent(group)}/duplicate`, {
      method: 'POST',
      body: JSON.stringify({ new_title }),
    }),
  renameGroup: (group: string, new_name?: string, new_number?: number) =>
    req<GroupResult>(`/groups/${encodeURIComponent(group)}`, {
      method: 'PATCH',
      body: JSON.stringify({ new_name, new_number }),
    }),

  // ── Événements ─────────────────────────────────────────────────────────

  listEvents: (group: string) =>
    req<{ group: string; events: string[] }>(`/groups/${encodeURIComponent(group)}/events`),
  listAllEvents: () => req<{ events: EventInfo[] }>('/events'),
  createEvent: (group: string, title: string) =>
    req<EventResult>('/events', { method: 'POST', body: JSON.stringify({ group, title }) }),
  deleteEvent: (group: string, event: string) =>
    req<EventResult>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}`, { method: 'DELETE' }),
  duplicateEvent: (group: string, event: string, new_title?: string) =>
    req<EventResult>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/duplicate`, {
      method: 'POST',
      body: JSON.stringify({ new_title }),
    }),

  // ── Slides ─────────────────────────────────────────────────────────────

  listSlides: (group: string, event: string) =>
    req<SlideInfo>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/slides`),
  getSlide: (group: string, event: string, slide: string) =>
    req<SlideContent>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/slides/${encodeURIComponent(slide)}`),
  createSlide: (group: string, event: string, data: SlideRequest) =>
    req<SlideContent>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/slides`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  updateSlideContent: (group: string, event: string, slide: string, content: string) =>
    req<SlideContent>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/slides/${encodeURIComponent(slide)}/content`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  deleteSlide: (group: string, event: string, slide: string) =>
    req<{ success: boolean }>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/slides/${encodeURIComponent(slide)}`, { method: 'DELETE' }),
  duplicateSlide: (group: string, event: string, slide: string, new_title?: string) =>
    req<{ success: boolean }>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/slides/${encodeURIComponent(slide)}/duplicate`, {
      method: 'POST',
      body: JSON.stringify({ new_title }),
    }),
  renameSlide: (group: string, event: string, slide: string, new_name?: string, new_number?: number, new_type?: string) =>
    req<{ success: boolean }>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/slides/${encodeURIComponent(slide)}`, {
      method: 'PATCH',
      body: JSON.stringify({ new_name, new_number, new_type }),
    }),

  // ── Live formateur ─────────────────────────────────────────────────────

  startLive: (data: StartLiveRequest) =>
    req<StartLiveResponse>('/live/start', { method: 'POST', body: JSON.stringify(data) }),
  liveStatus: (liveId: string) => req<LiveState>(`/live/${liveId}/status`),
  liveNext: (liveId: string) => req<LiveState>(`/live/${liveId}/next`, { method: 'POST' }),
  livePrevious: (liveId: string) => req<LiveState>(`/live/${liveId}/previous`, { method: 'POST' }),
  liveGoto: (liveId: string, number: number) =>
    req<LiveState>(`/live/${liveId}/goto`, { method: 'POST', body: JSON.stringify({ number }) }),
  liveStop: (liveId: string) => req<LiveState>(`/live/${liveId}/stop`, { method: 'POST' }),
  showCorrection: (liveId: string) => req<LiveState>(`/live/${liveId}/correction/show`, { method: 'POST' }),
  hideCorrection: (liveId: string) => req<LiveState>(`/live/${liveId}/correction/hide`, { method: 'POST' }),
  liveStudents: (liveId: string) => req<StudentsResponse>(`/live/${liveId}/students`),
  liveResults: (liveId: string) => req<ResultsResponse>(`/live/${liveId}/results`),
  liveStats: (liveId: string, all = false) =>
    req<StatsResponse | AllStatsResponse>(`/live/${liveId}/stats${all ? '?all=1' : ''}`),
  liveQuestions: (liveId: string) => req<QuestionsResponse>(`/live/${liveId}/questions`),
  liveReactions: (liveId: string) => req<ReactionsResponse>(`/live/${liveId}/reactions`),
  answerQuestion: (liveId: string, qid: number, text: string) =>
    req<{ success: boolean }>(`/live/${liveId}/questions/${qid}/answer`, { method: 'POST', body: JSON.stringify({ text }) }),
  toggleQuestion: (liveId: string, qid: number) =>
    req<{ success: boolean }>(`/live/${liveId}/questions/${qid}/toggle`, { method: 'POST' }),
  announce: (liveId: string, text: string) =>
    req<{ success: boolean }>(`/live/${liveId}/announce`, { method: 'POST', body: JSON.stringify({ text }) }),
  kickStudent: (liveId: string, pid: string) =>
    req<{ kicked: boolean }>(`/live/${liveId}/students/${pid}`, { method: 'DELETE' }),
  activeLives: () => req<ActiveLivesResponse>('/live/active'),
  eventSessions: (group: string, event: string) =>
    req<SessionsResponse>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/sessions`),

  // ── Étudiant ───────────────────────────────────────────────────────────

  studentJoin: (data: JoinRequest) =>
    req<JoinResponse>('/student/join', { method: 'POST', body: JSON.stringify(data) }, false),
  studentResume: (studentToken: string) =>
    req<JoinResponse>('/student/resume', {
      method: 'POST',
      headers: { Authorization: `Bearer ${studentToken}` },
    }),
  studentCurrent: (studentToken: string) =>
    req<StudentState>('/student/current', {
      headers: { Authorization: `Bearer ${studentToken}` },
    }),
  studentAnswer: (studentToken: string, answer: Record<string, unknown>) =>
    req<SubmitAnswerResponse>('/student/answers', {
      method: 'POST',
      headers: { Authorization: `Bearer ${studentToken}` },
      body: JSON.stringify({ answer }),
    }),
  studentNext: (studentToken: string) =>
    req<StudentState>('/student/next', {
      method: 'POST',
      headers: { Authorization: `Bearer ${studentToken}` },
    }),
  studentPrevious: (studentToken: string) =>
    req<StudentState>('/student/previous', {
      method: 'POST',
      headers: { Authorization: `Bearer ${studentToken}` },
    }),
  studentResults: (studentToken: string) =>
    req<Record<string, unknown>>('/student/results', {
      headers: { Authorization: `Bearer ${studentToken}` },
    }),
  studentAsk: (studentToken: string, text: string) =>
    req<{ success: boolean; question_id: number }>('/student/questions', {
      method: 'POST',
      headers: { Authorization: `Bearer ${studentToken}` },
      body: JSON.stringify({ text }),
    }),
  studentQuestions: (studentToken: string) =>
    req<QuestionsResponse>('/student/questions', {
      headers: { Authorization: `Bearer ${studentToken}` },
    }),
  studentReaction: (studentToken: string, emoji: string) =>
    req<{ success: boolean }>('/student/reaction', {
      method: 'POST',
      headers: { Authorization: `Bearer ${studentToken}` },
      body: JSON.stringify({ emoji }),
    }),

  // ── Médias ─────────────────────────────────────────────────────────────

  listMedia: (group: string, event: string) =>
    req<{ files: string[] }>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/media`),
  uploadMedia: (group: string, event: string, filename: string, data: Blob) =>
    req<{ success: boolean }>(
      `/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/media?filename=${encodeURIComponent(filename)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: data,
      }
    ),
  deleteMedia: (group: string, event: string, filename: string) =>
    req<{ success: boolean }>(`/groups/${encodeURIComponent(group)}/events/${encodeURIComponent(event)}/media/${encodeURIComponent(filename)}`, { method: 'DELETE' }),

  // ── Health ─────────────────────────────────────────────────────────────

  health: () => fetch('/health').then((r) => r.json()).catch(() => ({ status: 'offline', version: '' })) as Promise<{ status: string; version: string }>,
}

export { ApiError }
