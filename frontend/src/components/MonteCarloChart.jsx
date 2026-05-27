/**
 * MonteCarloChart — Monte Carlo P10/P50/P90 밴드 차트
 *
 * 왜 밴드 차트인가?
 *   단일 성장선("20년 후 배당 30만원")보다
 *   "85% 확률로 20만~50만원 사이" 라는 신뢰구간이
 *   투자자에게 훨씬 정직하고 설득력 있는 정보다.
 *
 * 구성:
 *   - P10 (비관): 하위 10% 시나리오 (빨간 점선)
 *   - P50 (기준): 중앙값 시나리오 (흰 실선)
 *   - P90 (낙관): 상위 10% 시나리오 (초록 점선)
 *   - 밴드 영역: P10~P90 사이 반투명 채움
 *   - 목표선: 월 목표 배당금 기준선
 */
import {
  ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer, Legend,
} from 'recharts'

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  const p10 = payload.find(p => p.dataKey === 'p10')?.value
  const p50 = payload.find(p => p.dataKey === 'p50')?.value
  const p90 = payload.find(p => p.dataKey === 'p90')?.value

  return (
    <div style={{
      background: '#1e293b', border: '1px solid #334155',
      borderRadius: 10, padding: '10px 14px', fontSize: 12, color: '#e2e8f0',
    }}>
      <div style={{ fontWeight: 700, marginBottom: 6, color: '#94a3b8' }}>
        {label}년차
      </div>
      <div style={{ color: '#34d399' }}>낙관(P90): {p90?.toFixed(1)}만원</div>
      <div style={{ color: '#e2e8f0', fontWeight: 600 }}>기준(P50): {p50?.toFixed(1)}만원</div>
      <div style={{ color: '#ef4444' }}>비관(P10): {p10?.toFixed(1)}만원</div>
    </div>
  )
}

export default function MonteCarloChart({ monteCarlo, monthlyTarget }) {
  if (!monteCarlo?.p50_monthly) return null

  const { p10_monthly, p50_monthly, p90_monthly, years } = monteCarlo

  // recharts용 데이터 조립
  const data = (years || p50_monthly.map((_, i) => i + 1)).map((yr, i) => ({
    year:  yr,
    p10:   parseFloat((p10_monthly[i] || 0).toFixed(2)),
    p50:   parseFloat((p50_monthly[i] || 0).toFixed(2)),
    p90:   parseFloat((p90_monthly[i] || 0).toFixed(2)),
    band:  [
      parseFloat((p10_monthly[i] || 0).toFixed(2)),
      parseFloat((p90_monthly[i] || 0).toFixed(2)),
    ],
  }))

  const finalP50  = monteCarlo.p50_final || p50_monthly[p50_monthly.length - 1] || 0
  const finalP10  = monteCarlo.p10_final || p10_monthly[p10_monthly.length - 1] || 0
  const achievePct = monteCarlo.confidence_at_target || 0
  const cutEvents  = monteCarlo.expected_cut_events || 0
  const regime     = monteCarlo.macro_regime_applied || ''

  return (
    <div style={{
      background: '#0f172a', borderRadius: 16, padding: '20px 24px',
      border: '1px solid #1e293b',
    }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>
            Monte Carlo 시뮬레이션
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
            1,000회 시뮬레이션 · 20년 월 배당 신뢰구간
            {regime && <span style={{ color: '#6366f1', marginLeft: 8 }}>({regime} 반영)</span>}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 11, color: '#64748b' }}>목표달성 확률</div>
          <div style={{
            fontSize: 22, fontWeight: 800,
            color: achievePct >= 70 ? '#34d399' : achievePct >= 50 ? '#fbbf24' : '#ef4444',
          }}>
            {achievePct.toFixed(0)}%
          </div>
        </div>
      </div>

      {/* 밴드 차트 */}
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={data} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
          <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
          <XAxis
            dataKey="year"
            tick={{ fill: '#64748b', fontSize: 11 }}
            tickFormatter={v => `${v}년`}
          />
          <YAxis
            tick={{ fill: '#64748b', fontSize: 11 }}
            tickFormatter={v => `${v}만`}
            width={45}
          />
          <Tooltip content={<CustomTooltip />} />

          {/* P10~P90 밴드 */}
          <Area
            dataKey="p90"
            stroke="none"
            fill="#14532d"
            fillOpacity={0.3}
            legendType="none"
          />
          <Area
            dataKey="p10"
            stroke="none"
            fill="#0f172a"
            fillOpacity={1}
            legendType="none"
          />

          {/* P90 상단선 */}
          <Line
            dataKey="p90"
            stroke="#34d399"
            strokeDasharray="4 3"
            strokeWidth={1.5}
            dot={false}
            name="낙관(P90)"
          />
          {/* P50 중앙선 */}
          <Line
            dataKey="p50"
            stroke="#e2e8f0"
            strokeWidth={2.5}
            dot={false}
            name="기준(P50)"
          />
          {/* P10 하단선 */}
          <Line
            dataKey="p10"
            stroke="#ef4444"
            strokeDasharray="4 3"
            strokeWidth={1.5}
            dot={false}
            name="비관(P10)"
          />

          {/* 목표 배당 기준선 */}
          {monthlyTarget > 0 && (
            <ReferenceLine
              y={monthlyTarget}
              stroke="#6366f1"
              strokeDasharray="6 3"
              label={{ value: `목표 ${monthlyTarget}만`, fill: '#818cf8', fontSize: 11, position: 'insideTopRight' }}
            />
          )}

          <Legend
            wrapperStyle={{ fontSize: 12, color: '#94a3b8', paddingTop: 8 }}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* 하단 요약 카드 */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 8, marginTop: 14,
      }}>
        {[
          {
            label: '20년 후 기준(P50)',
            value: `${finalP50.toFixed(1)}만원/월`,
            color: '#e2e8f0',
          },
          {
            label: '비관 시나리오(P10)',
            value: `${finalP10.toFixed(1)}만원/월`,
            color: '#ef4444',
            sub: `P50 대비 -${((1 - finalP10 / Math.max(finalP50, 0.01)) * 100).toFixed(0)}%`,
          },
          {
            label: '예상 배당컷 횟수',
            value: `${cutEvents.toFixed(1)}회`,
            color: cutEvents >= 3 ? '#ef4444' : cutEvents >= 1 ? '#fbbf24' : '#34d399',
            sub: '20년간 평균',
          },
        ].map(card => (
          <div key={card.label} style={{
            background: '#1e293b', borderRadius: 8, padding: '10px 12px',
          }}>
            <div style={{ fontSize: 10, color: '#64748b', marginBottom: 4 }}>{card.label}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: card.color }}>{card.value}</div>
            {card.sub && <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>{card.sub}</div>}
          </div>
        ))}
      </div>

      {/* 경고 메시지 */}
      {monteCarlo.summary_message && (
        <div style={{
          marginTop: 12, fontSize: 12, color: '#94a3b8',
          padding: '8px 12px', background: '#1e293b', borderRadius: 8,
          borderLeft: '3px solid #6366f1',
        }}>
          {monteCarlo.summary_message}
        </div>
      )}
    </div>
  )
}
