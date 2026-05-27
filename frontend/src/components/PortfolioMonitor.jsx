import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts'

function formatDday(dateString) {
  if (!dateString) return 'D-?'
  const target = new Date(dateString)
  if (Number.isNaN(target.getTime())) return 'D-?'
  const today = new Date()
  const ms = target.setHours(0, 0, 0, 0) - today.setHours(0, 0, 0, 0)
  const d = Math.ceil(ms / (1000 * 60 * 60 * 24))
  return d >= 0 ? `D-${d}` : `D+${Math.abs(d)}`
}

function projection10y(projection) {
  const years = projection?.years || []
  const monthly = projection?.monthly_div_net || []
  return years
    .slice(0, 10)
    .map((y, i) => ({ year: `Y${y}`, monthly: monthly[i] ?? 0 }))
}

export default function PortfolioMonitor({
  calendar = {},
  rebalancingPlan = {},
  recommendations = [],
  projection = {},
}) {
  const thisMonthDiv = calendar?.monthly_totals?.[new Date().getMonth()] || 0
  const nextDate = rebalancingPlan?.next_date || rebalancingPlan?.next_rebalance_date
  const changed = (recommendations || []).filter(
    (r) => r.ml_status && r.ml_status !== 'INTACT'
  )
  const curve = projection10y(projection)

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4" style={{ display: 'grid', gap: 12, marginTop: 14 }}>
      <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 14 }}>
        <div style={{ color: '#94a3b8', fontSize: 12 }}>이번 달 받을 배당</div>
        <div style={{ color: '#e2e8f0', fontSize: 30, fontWeight: 800, marginTop: 4 }}>
          {Math.round(thisMonthDiv)}만원
        </div>
      </div>

      <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 14 }}>
        <div style={{ color: '#94a3b8', fontSize: 12 }}>다음 리밸런싱 권장일</div>
        <div style={{ color: '#f8fafc', fontSize: 18, fontWeight: 700, marginTop: 6 }}>
          {nextDate || '데이터 없음'} ({formatDday(nextDate)})
        </div>
      </div>

      <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 14 }}>
        <div style={{ color: '#94a3b8', fontSize: 12, marginBottom: 8 }}>종목별 ML 점수 변화</div>
        {changed.length ? (
          changed.slice(0, 5).map((r) => (
            <div key={r.ticker} style={{ color: '#e2e8f0', fontSize: 12, marginBottom: 6 }}>
              {r.name} ({r.ticker}) · {r.ml_status} · score {r.ml_score ?? '-'}
            </div>
          ))
        ) : (
          <div style={{ color: '#64748b', fontSize: 12 }}>변경 감지 종목 없음</div>
        )}
      </div>

      <div style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 12, padding: 14 }}>
        <div style={{ color: '#94a3b8', fontSize: 12, marginBottom: 8 }}>배당 성장 곡선 (10년)</div>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={curve}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="year" tick={{ fontSize: 11, fill: '#94a3b8' }} />
            <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} />
            <Tooltip />
            <Line type="monotone" dataKey="monthly" stroke="#34d399" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
