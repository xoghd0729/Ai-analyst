/**
 * HealthRadarChart — Portfolio Health OS 6축 레이더 차트
 *
 * 왜 레이더 차트인가?
 *   수치 나열(표)보다 6개 축의 균형 상태를 한눈에 파악 가능.
 *   "어느 축이 약한가"를 시각적으로 즉시 인지할 수 있다.
 *
 * 6축 구성:
 *   stability       / 안정성    (max 25)
 *   growth          / 성장성    (max 20)
 *   cashflow        / 현금흐름  (max 15)
 *   cashflow_smooth / 배당균등도 (max 10)
 *   inflation_defense / 인플레방어 (max 15)
 *   tax_efficiency  / 세금효율  (max 10)
 *   diversification / 분산도    (max 15)
 */
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  PolarRadiusAxis, ResponsiveContainer, Tooltip, Legend,
} from 'recharts'

const AXIS_LABELS = {
  stability:         '안정성',
  growth:            '성장성',
  cashflow:          '현금흐름',
  cashflow_smooth:   '배당균등도',
  inflation_defense: '인플레방어',
  tax_efficiency:    '세금효율',
  diversification:   '분산도',
}

const GRADE_COLOR = {
  'S': '#10b981',  // 에메랄드
  'A': '#059669',
  'B': '#d97706',
  'C': '#f97316',
  'D': '#ef4444',
}

function getGradeColor(grade) {
  return GRADE_COLOR[grade?.[0]] || '#6366f1'
}

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  return (
    <div style={{
      background: '#fff', border: '1px solid #e3e8f2', boxShadow: '0 6px 20px rgba(15,42,92,.12)',
      borderRadius: 10, padding: '10px 14px', fontSize: 13, color: '#283143',
    }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>{d?.fullLabel}</div>
      <div style={{ color: 'var(--text-sub)' }}>
        {d?.score} / {d?.max}점 ({d?.pct}%)
      </div>
      {d?.action && (
        <div style={{ marginTop: 6, color: '#d97706', fontSize: 12 }}>
          {d.action}
        </div>
      )}
    </div>
  )
}

export default function HealthRadarChart({ health }) {
  if (!health?.axes) return null

  const { total_score, max_score, grade, radar_data, axes } = health

  // recharts RadarChart 용 데이터 변환
  const data = (radar_data || []).map(item => ({
    subject:   AXIS_LABELS[item.axis] || item.axis,
    fullLabel: AXIS_LABELS[item.axis] || item.axis,
    value:     item.pct,          // 0~100% 표준화
    score:     item.score,
    max:       item.max,
    pct:       item.pct,
    action:    axes?.[item.axis]?.action || '',
  }))

  const gradeColor = getGradeColor(grade)
  const totalPct   = max_score ? Math.round(total_score / max_score * 100) : 0

  return (
    <div style={{
      background: '#ffffff', borderRadius: 16, padding: '20px 24px',
      border: '1px solid #dfe3ea',
    }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#283143' }}>
            Portfolio Health OS
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
            6축 종합 건강도 분석
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{
            fontSize: 32, fontWeight: 800, color: gradeColor,
            lineHeight: 1,
          }}>
            {grade}
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-sub)', marginTop: 2 }}>
            {total_score} / {max_score}점 ({totalPct}%)
          </div>
        </div>
      </div>

      {/* 레이더 차트 */}
      <ResponsiveContainer width="100%" height={280}>
        <RadarChart data={data} margin={{ top: 10, right: 30, bottom: 10, left: 30 }}>
          <PolarGrid stroke="#dfe3ea" />
          <PolarAngleAxis
            dataKey="subject"
            tick={{ fill: 'var(--text-sub)', fontSize: 12 }}
          />
          <PolarRadiusAxis
            angle={90} domain={[0, 100]}
            tick={{ fill: '#475569', fontSize: 10 }}
            tickCount={4}
          />
          <Radar
            name="건강도"
            dataKey="value"
            stroke={gradeColor}
            fill={gradeColor}
            fillOpacity={0.2}
            strokeWidth={2}
          />
          <Tooltip content={<CustomTooltip />} />
        </RadarChart>
      </ResponsiveContainer>

      {/* 6축 상세 바 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', marginTop: 12 }}>
        {data.map(d => (
          <div key={d.subject}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 3 }}>
              <span style={{ color: 'var(--text-sub)' }}>{d.subject}</span>
              <span style={{ color: d.pct >= 70 ? '#059669' : d.pct >= 40 ? '#d97706' : '#ef4444', fontWeight: 600 }}>
                {d.score}/{d.max}
              </span>
            </div>
            <div style={{ height: 4, background: '#dfe3ea', borderRadius: 2 }}>
              <div style={{
                height: '100%', borderRadius: 2,
                width: `${d.pct}%`,
                background: d.pct >= 70 ? '#059669' : d.pct >= 40 ? '#d97706' : '#ef4444',
                transition: 'width 0.6s ease',
              }} />
            </div>
          </div>
        ))}
      </div>

      {/* 팁 */}
      {health.tips?.length > 0 && (
        <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid #dfe3ea' }}>
          {health.tips.slice(0, 2).map((tip, i) => (
            <div key={i} style={{ fontSize: 12, color: '#d97706', marginTop: i > 0 ? 6 : 0 }}>
              {tip}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
