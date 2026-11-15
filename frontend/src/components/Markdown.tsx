// Rend le contenu Markdown d'une slide avec react-markdown + GFM.
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function Markdown({ content }: { content: string }) {
  return (
    <div className="prose prose-lg max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-li:text-gray-700">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
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
