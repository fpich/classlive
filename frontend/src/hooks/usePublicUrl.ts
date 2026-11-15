// URL publique d'exposition (lue depuis expose.conf côté backend via /api/v1/public-url).
// Si non configurée, fallback sur window.location.origin.
import { useState, useEffect } from 'react'

export function usePublicUrl(): string {
  const [url, setUrl] = useState<string>(window.location.origin)

  useEffect(() => {
    fetch('/api/v1/public-url')
      .then((r) => r.json())
      .then((d) => { if (d.public_url) setUrl(d.public_url.replace(/\/$/, '')) })
      .catch(() => {})
  }, [])

  return url
}

// Construit l'URL de jonction avec le bon base path (/app en prod).
export function buildJoinUrl(code: string, publicUrl: string): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '') // '/app' en prod
  return `${publicUrl}${base}/join?code=${code}`
}
