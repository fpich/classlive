// Rend le contenu Markdown d'une slide avec react-markdown + GFM.
// Supporte les callouts Obsidian (> [!type] ...) rendus comme des cartes stylées.
import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Extrait le texte brut d'un nœud React (récursif), pour détecter le type de callout.
function extractText(node: React.ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (React.isValidElement(node)) {
    return extractText((node.props as { children?: React.ReactNode }).children)
  }
  return ''
}

const CALLOUT_RE = /^\[!([a-zéèêàâçûù]+)\]\s*(.*)$/i

function Callout({ children }: { children?: React.ReactNode }) {
  const kids = React.Children.toArray(children)
  const first = kids[0] as React.ReactElement | undefined
  const text = first ? extractText(first) : ''
  const m = text.match(CALLOUT_RE)

  if (!m) {
    // Pas un callout : blockquote classique.
    return <blockquote>{children}</blockquote>
  }

  const type = m[1].toLowerCase()
  const title = m[2] || type
  const rest = kids.slice(1)

  return (
    <div className={`callout callout-${type}`} data-callout={type}>
      <div className="callout-title">
        <span className="callout-icon" aria-hidden="true" />
        <span className="callout-title-inner">{title}</span>
      </div>
      <div className="callout-content">{rest}</div>
    </div>
  )
}

export default function Markdown({ content }: { content: string }) {
  return (
    <div className="slide-content prose prose-lg max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-li:text-gray-700">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          blockquote: Callout,
          img: ({ src, alt }) => (
            <img src={src} alt={alt} className="max-w-full rounded-lg shadow-sm" />
          ),
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-brand-600 underline">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}
