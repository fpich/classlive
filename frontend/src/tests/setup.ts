// Configuration de base pour les tests Vitest
import '@testing-library/jest-dom'

// Mock pour les WebSockets
class MockWebSocket {
  onopen: (() => void) | null = null
  onclose: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null

  send(_data: unknown) {}
  close() {}
}

// @ts-expect-error - Remplacement du WebSocket global
global.WebSocket = MockWebSocket as typeof WebSocket

// Mock pour navigator.clipboard
Object.assign(navigator, {
  clipboard: {
    writeText: vi.fn().mockResolvedValue(undefined),
    readText: vi.fn().mockResolvedValue(''),
  }
})

// Mock pour window.location
Object.defineProperty(window, 'location', {
  value: {
    href: 'http://localhost:8080/app',
    origin: 'http://localhost:8080',
    hostname: 'localhost',
    port: '8080',
    pathname: '/app',
    search: '',
    hash: '',
    reload: vi.fn(),
    replace: vi.fn(),
    assign: vi.fn()
  },
  writable: true
})
