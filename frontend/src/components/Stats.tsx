// Composants d'affichage des statistiques agrégées pour le formateur.
import type { StatsResponse, AllStatsResponse, SlideStats } from '@/types/api'

export function StatsBars({ stats }: { stats: StatsResponse | SlideStats }) {
  if (stats.options) {
    const entries = Object.entries(stats.options).sort((a, b) => b[1] - a[1])
    const max = Math.max(...entries.map(([, v]) => v), 1)
    return (
      <div className="space-y-2">
        {entries.map(([opt, count]) => (
          <div key={opt} className="flex items-center gap-2">
            <span className="w-8 font-bold text-gray-700">{opt}</span>
            <div className="flex-1 bg-gray-100 rounded-full h-6 overflow-hidden">
              <div
                className="bg-brand-500 h-full rounded-full transition-all duration-500 flex items-center justify-end pr-2"
                style={{ width: `${(count / max) * 100}%` }}
              >
                {count > 0 && <span className="text-white text-xs font-medium">{count}</span>}
              </div>
            </div>
            <span className="text-sm text-gray-500 w-16 text-right">
              {stats.total_students > 0 ? Math.round((count / stats.total_students) * 100) : 0}%
            </span>
          </div>
        ))}
      </div>
    )
  }
  if (stats.words) {
    const entries = Object.entries(stats.words).sort((a, b) => b[1] - a[1])
    const max = Math.max(...entries.map(([, v]) => v), 1)
    return (
      <div className="flex flex-wrap gap-2">
        {entries.map(([word, count]) => (
          <span
            key={word}
            className="px-3 py-1 bg-brand-100 text-brand-800 rounded-full font-medium"
            style={{ fontSize: `${Math.max(0.8, Math.min(2, 0.8 + (count / max) * 1.2))}rem` }}
          >
            {word} ({count})
          </span>
        ))}
      </div>
    )
  }
  if (stats.values) {
    const entries = Object.entries(stats.values).sort((a, b) => Number(a[0]) - Number(b[0]))
    const max = Math.max(...entries.map(([, v]) => v), 1)
    return (
      <div className="flex gap-2 items-end h-24">
        {entries.map(([val, count]) => (
          <div key={val} className="flex flex-col items-center gap-1 flex-1">
            <div
              className="w-full bg-brand-500 rounded-t transition-all duration-500"
              style={{ height: `${(count / max) * 80}%` }}
            />
            <span className="text-xs font-medium text-gray-700">{val}</span>
            <span className="text-xs text-gray-400">{count}</span>
          </div>
        ))}
      </div>
    )
  }
  // F (texte libre) ou compteur simple
  return (
    <div className="text-center py-4">
      <span className="text-4xl font-bold text-brand-600">{stats.answered}</span>
      <span className="text-gray-500"> / {stats.total_students} réponses</span>
    </div>
  )
}

export function AllSlidesStats({ data }: { data: AllStatsResponse }) {
  return (
    <div className="space-y-4">
      {data.slides.map((s) => (
        <div key={s.slide} className="border-b border-gray-100 pb-4 last:border-0">
          <div className="flex items-center gap-2 mb-2">
            <span className="font-medium text-gray-800">{s.slide}</span>
            <span className="text-xs text-gray-400">{s.slide_type}</span>
            <span className="text-xs text-gray-400 ml-auto">{s.answered}/{s.total_students}</span>
          </div>
          <StatsBars stats={s} />
        </div>
      ))}
    </div>
  )
}
