// Client WebSocket ClassLive avec reconnexion automatique et heartbeat ping.
import type { WSEvent } from '@/types/api'

type Handler = (event: WSEvent) => void

export class ClassLiveWS {
  private ws: WebSocket | null = null
  private handlers: Handler[] = []
  private token: string
  private path: string
  private reconnectDelay = 1000
  private maxReconnectDelay = 15000
  private pingInterval: ReturnType<typeof setInterval> | null = null
  private shouldReconnect = true
  private connected = false

  constructor(token: string, path: string) {
    this.token = token
    this.path = path
  }

  onMessage(handler: Handler) {
    this.handlers.push(handler)
  }

  connect() {
    this.shouldReconnect = true
    this._doConnect()
  }

  private _doConnect() {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // En dev, Vite proxy /ws vers le backend. En prod, même origine.
    const wsPath = this.path.startsWith('/api') ? this.path : `/api/v1${this.path}`
    const url = `${proto}//${window.location.host}${wsPath}`
    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      this.connected = true
      this.reconnectDelay = 1000
      // Authentification : premier message = token
      this.ws?.send(JSON.stringify({ token: this.token }))
      // Heartbeat ping toutes les 20 secondes
      this.pingInterval = setInterval(() => {
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ event: 'ping' }))
        }
      }, 20000)
    }

    this.ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as WSEvent
        this.handlers.forEach((h) => h(data))
      } catch {
        // ignore malformed
      }
    }

    this.ws.onclose = () => {
      this.connected = false
      if (this.pingInterval) clearInterval(this.pingInterval)
      if (this.shouldReconnect) {
        setTimeout(() => this._doConnect(), this.reconnectDelay)
        this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxReconnectDelay)
      }
    }

    this.ws.onerror = () => {
      // onclose suivra
    }
  }

  send(data: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  isConnected() {
    return this.connected
  }

  close() {
    this.shouldReconnect = false
    if (this.pingInterval) clearInterval(this.pingInterval)
    this.ws?.close()
  }
}
