// Types correspondant au contrat OpenAPI du backend ClassLive v1.0.0.
// Générés manuellement depuis backend/README.md et le code source.

export type SlideType = 'C' | 'A' | 'O' | 'R' | 'Q' | 'T' | 'F' | 'P' | 'N' | 'L' | 'I'

export const SLIDE_TYPE_LABELS: Record<SlideType, string> = {
  C: 'Contenu',
  Q: 'QCM',
  P: 'Sondage',
  A: 'Association',
  O: 'Ordre',
  R: 'Catégories',
  T: 'Texte à trous',
  F: 'Texte libre',
  N: 'Nuage de mots',
  L: 'Échelle 1-5',
  I: 'Pin sur image',
}

export const EXERCISE_TYPES: SlideType[] = ['A', 'O', 'R', 'Q', 'T', 'F', 'P', 'N', 'L', 'I']

export function isExercise(type: string): boolean {
  return EXERCISE_TYPES.includes(type as SlideType)
}

// ── Auth ──────────────────────────────────────────────────────────────────

export interface LoginRequest {
  username: string
  password: string
}

export interface LoginResponse {
  access_token: string
  token_type: string
  expires_in: number
  role: string
}

// ── Groupes / Événements ──────────────────────────────────────────────────

export interface GroupResult {
  success: boolean
  group: string
  created: boolean
  path: string
}

export interface EventResult extends GroupResult {
  title: string
}

export interface EventInfo {
  group: string
  title: string
}

// ── Slides ────────────────────────────────────────────────────────────────

export interface SlideRequest {
  title: string
  slide_type: SlideType
  content: string
  number?: number
}

export interface SlideInfo {
  group: string
  event: string
  slides: string[]
}

export interface SlideContent {
  group: string
  event: string
  slide: string
  content: string
  path: string
}

// ── Live ──────────────────────────────────────────────────────────────────

export type LiveMode = 'live' | 'autonome'
export type TimingMode = 'none' | 'par_question' | 'par_evenement'
export type CorrectionMode = 'jamais' | 'après_question' | 'à_la_fin' | 'show'

export interface StartLiveRequest {
  group: string
  title: string
  mode?: LiveMode
  timing?: TimingMode
  timing_seconds?: number
  correction?: string
  start_at?: string
  anonymous?: boolean
  reactions_enabled?: boolean
  questions_enabled?: boolean
}

export interface StartLiveResponse {
  live_id: string
  session_code: string
  group: string
  event: string
  current_slide: string
  status: string
  started_at: string
  mode: LiveMode
  timing: TimingMode
  timing_seconds: number | null
  correction_mode: CorrectionMode
  anonymous: boolean
  join_url: string
  reactions_enabled: boolean
  questions_enabled: boolean
}

export interface LiveState {
  live_id: string
  status: string
  mode: LiveMode
  group: string
  event: string
  slide: string
  slide_type: string
  number: number
  position: number
  total: number
  revision: number
  timing: TimingMode
  timing_seconds: number | null
  correction_mode: CorrectionMode
  deadline: string | null
  announcement: string | null
  anonymous: boolean
  orientation: 'paysage' | 'portrait'
  correction_visible: boolean
  reactions_enabled: boolean
  questions_enabled: boolean
  content?: string
  correction?: unknown
}

export interface StudentState {
  live_id: string
  status: string
  mode: LiveMode
  group: string
  event: string
  slide: string
  slide_type: string
  number: number
  position: number
  total: number
  revision: number
  online: number
  announcement: string | null
  orientation: 'paysage' | 'portrait'
  reactions_enabled: boolean
  questions_enabled: boolean
  content: string
  finished: boolean
  locked?: boolean
  expires_at?: string
  time_expired?: boolean
  question_started_at?: string
  correction_visible?: boolean
  correction?: unknown
}

// ── Étudiant ──────────────────────────────────────────────────────────────

export interface JoinRequest {
  session_code: string
  nom: string
  prenom: string
}

export interface JoinResponse {
  student_session_id: string
  participation_id: string
  live_id: string
  nom: string
  prenom: string
  mode: LiveMode
  current: StudentState
}

export interface SubmitAnswerRequest {
  answer: Record<string, unknown>
}

export interface SubmitAnswerResponse {
  success: boolean
  slide: string
  submitted_at: string
  saved: boolean
  locked: boolean
}

// ── Résultats / Stats ─────────────────────────────────────────────────────

export interface StudentInfo {
  participation_id: string
  nom: string
  prenom: string
  status: string
  joined_at: string
  last_seen: string
  answered: number
}

export interface StudentsResponse {
  live_id: string
  total_students: number
  connected: number
  disconnected: number
  students: StudentInfo[]
}

export interface AnswerEntry {
  slide: string
  answer: Record<string, unknown>
  submitted_at: string
}

export interface StudentResult {
  participation_id: string
  nom: string
  prenom: string
  answered: number
  answers: AnswerEntry[]
}

export interface ResultsResponse {
  live_id: string
  group: string
  event: string
  status: string
  started_at: string
  ended_at: string | null
  anonymous: boolean
  results: StudentResult[]
}

export interface SlideStats {
  number?: number
  slide: string
  slide_type: string
  answered: number
  total_students: number
  options?: Record<string, number>
  words?: Record<string, number>
  values?: Record<string, number>
  pins?: [number, number][]
  center?: { x: number; y: number }
}

export interface StatsResponse {
  live_id: string
  slide: string
  slide_type: string
  answered: number
  total_students: number
  options?: Record<string, number>
  words?: Record<string, number>
  values?: Record<string, number>
  pins?: [number, number][]
  center?: { x: number; y: number }
}

export interface AllStatsResponse {
  live_id: string
  slides: SlideStats[]
}

// ── Q&A ───────────────────────────────────────────────────────────────────

export interface Question {
  id: number
  participation_id: string
  nom: string
  prenom: string
  text: string
  asked_at: string
  answered: boolean
  answer_text: string | null
  answered_at: string | null
}

export interface QuestionsResponse {
  questions: Question[]
}

// ── Réactions ─────────────────────────────────────────────────────────────

export interface ReactionsResponse {
  counts: Record<string, number>
}

// ── Sessions ──────────────────────────────────────────────────────────────

export interface SessionInfo {
  id: string
  started_at: string
  ended_at: string | null
  status: string
  mode: string
}

export interface SessionsResponse {
  group: string
  event: string
  sessions: SessionInfo[]
}

export interface ActiveLive {
  id: string
  code: string
  group_name: string
  event_name: string
  started_at: string
  current_number: number
  mode: string
  timing: string
  timing_seconds: number | null
  correction_mode: string
}

export interface ActiveLivesResponse {
  lives: ActiveLive[]
}

// ── WebSocket events ──────────────────────────────────────────────────────

export type WSEvent =
  | { event: 'current'; current: StudentState }
  | { event: 'slide_changed'; current: StudentState | LiveState }
  | { event: 'correction_shown'; current: LiveState }
  | { event: 'correction_hidden'; current: LiveState }
  | { event: 'live_ended'; live_id: string }
  | { event: 'session_ended'; live_id: string }
  | { event: 'answer_received'; participation_id: string }
  | { event: 'answer_locked'; slide: string }
  | { event: 'student_joined'; participation_id: string }
  | { event: 'student_connected'; participation_id: string }
  | { event: 'student_disconnected'; participation_id: string }
  | { event: 'student_kicked'; participation_id: string }
  | { event: 'student_finished'; participation_id: string }
  | { event: 'question_asked'; participation_id: string; question_id: number; nom: string; prenom: string }
  | { event: 'question_answered'; question_id: number; answer_text: string; answered_at: string }
  | { event: 'question_updated'; question_id: number; answered: boolean }
  | { event: 'reaction'; participation_id: string; emoji: string; counts: Record<string, number> }
  | { event: 'announcement'; text: string }
  | { event: 'orientation_changed'; current: LiveState }
  | { event: 'monitor'; students: StudentsResponse; current: LiveState }
  | { event: 'pong' }
  | { event: 'error'; detail: string }
