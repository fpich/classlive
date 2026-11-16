// Rend le contenu Markdown d'une slide avec react-markdown + GFM.
// Supporte les callouts Obsidian (> [!type] ...) rendus comme des cartes stylées.
import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

// Détecte le marqueur de callout en début de ligne.
// Le flag m (multiline) est indispensable : react-markdown fusionne la ligne
// « > [!type] titre » et la première ligne de contenu dans un même <p>,
// séparées par un \n. Sans lui, le $ ne matche jamais (le . ne traverse pas \n).
const CALLOUT_RE = /^\[!([a-zéèêàâçûù]+)\]\s*(.*)$/im

// Analyse les enfants d'un blockquote. Retourne { type, title, content } si
// c'est un callout Obsidian, sinon null (blockquote classique).
function parseCallout(children: React.ReactNode): {
  type: string
  title: string
  content: React.ReactNode
} | null {
  const kids = React.Children.toArray(children)

  // Le premier enfant est souvent un \n ; on cherche le premier élément réel.
  const firstIdx = kids.findIndex((c) => React.isValidElement(c))
  if (firstIdx === -1) return null
  const first = kids[firstIdx] as React.ReactElement

  // Le premier élément est un <p> dont le premier nœud texte contient le marqueur.
  const pChildren = React.Children.toArray(
    (first.props as { children?: React.ReactNode }).children
  )
  const firstText = pChildren[0]
  if (typeof firstText !== 'string') return null

  const m = firstText.match(CALLOUT_RE)
  if (!m) return null

  const type = m[1].toLowerCase()
  const title = m[2] || type

  // Retire la ligne du marqueur du premier <p> et garde le reste comme contenu.
  const nlIdx = firstText.indexOf('\n')
  const restOfFirstText = nlIdx !== -1 ? firstText.slice(nlIdx + 1) : ''
  const rebuilt = [restOfFirstText, ...pChildren.slice(1)].filter((c) => c !== '')

  const content: React.ReactNode[] = []
  if (rebuilt.length > 0) {
    content.push(React.cloneElement(first, { children: rebuilt }))
  }
  content.push(...kids.slice(firstIdx + 1))

  return { type, title, content }
}

function Callout({ children }: { children?: React.ReactNode }) {
  const parsed = parseCallout(children)
  if (!parsed) {
    // Pas un callout : blockquote classique.
    return <blockquote>{children}</blockquote>
  }

  return (
    <div className={`callout callout-${parsed.type}`} data-callout={parsed.type}>
      <div className="callout-title">
        <span className="callout-icon" aria-hidden="true" />
        <span className="callout-title-inner">{parsed.title}</span>
      </div>
      <div className="callout-content">{parsed.content}</div>
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
