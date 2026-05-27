/**
 * CashflowMilestone — "내 인생이 어떻게 변하나" UX 컴포넌트
 *
 * 피드백에서 가장 강조한 부분:
 *   "사용자가 결국 뭘 얻는지" 가 흐려진다.
 *   통신비 달성, 월세 커버, 생활비 50%, 경제적 자유 —
 *   이걸 보여주는 게 핵심 UX 임팩트.
 *
 * 마일스톤 5단계:
 *   30만원  → 통신비·구독료 자동화
 *   80만원  → 교통비·식비 커버
 *   150만원 → 주거비+식비 커버 (Lean FIRE)
 *   300만원 → 생활비 100% 커버
 *   500만원 → 경제적 자유
 */

const MILESTONES = [
  { amount: 30,  icon: '📱', label: '통신비 자동화',     desc: '매달 통신비·구독료가 배당으로 해결',   color: '#6366f1' },
  { amount: 80,  icon: '🍽️', label: '식비·교통비 커버', desc: '월 80만원 → 교통+식비 완전 자동화',    color: '#3b82f6' },
  { amount: 150, icon: '🏠', label: 'Lean FIRE 진입',   desc: '주거비+생활비 50% 배당으로 조달',      color: '#0ea5e9' },
  { amount: 300, icon: '🎯', label: '생활비 100% 커버', desc: '배당만으로 모든 생활비 조달 가능',      color: '#10b981' },
  { amount: 500, icon: '🏝️', label: '경제적 자유',      desc: '월 500만원 — 일 없이도 풍요로운 삶',   color: '#f59e0b' },
]

function getProjectionAge(fire_plan, label) {
  if (!fire_plan) return null
  const types = fire_plan.fire_types || {}
  for (const [, v] of Object.entries(types)) {
    if (v?.label === label || v?.monthly_target_만원 <= (label === 'Lean FIRE 진입' ? 150 : 9999)) {
      return v?.achievable_at_age
    }
  }
  return null
}

export default function CashflowMilestone({ summary, fire_plan }) {
  const currentMonthly = summary?.est_monthly_div_after_tax_만원 || 0
  const projection20   = summary?.projection_20y_monthly || 0

  return (
    <div style={{
      background: '#0f172a', borderRadius: 16, padding: '20px 24px',
      border: '1px solid #1e293b',
    }}>
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0' }}>
          현금흐름 마일스톤
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
          지금 배당으로 내 삶이 어떻게 바뀌는가
        </div>
      </div>

      {/* 현재 월 배당 큰 숫자 */}
      <div style={{
        textAlign: 'center', padding: '16px 0', marginBottom: 16,
        borderBottom: '1px solid #1e293b',
      }}>
        <div style={{ fontSize: 12, color: '#64748b' }}>현재 월 배당 (세후)</div>
        <div style={{ fontSize: 40, fontWeight: 900, color: '#34d399', lineHeight: 1.1 }}>
          {currentMonthly.toFixed(1)}
          <span style={{ fontSize: 16, fontWeight: 400, color: '#64748b' }}>만원</span>
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginTop: 4 }}>
          연간 {(currentMonthly * 12).toFixed(0)}만원 배당 수령
        </div>
      </div>

      {/* 마일스톤 목록 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {MILESTONES.map(ms => {
          const achieved  = currentMonthly >= ms.amount
          const inRange   = !achieved && currentMonthly >= ms.amount * 0.5
          const pct       = Math.min(currentMonthly / ms.amount * 100, 100)

          return (
            <div key={ms.amount} style={{
              background: achieved ? '#0f2a1f' : '#111827',
              borderRadius: 12,
              padding: '12px 14px',
              border: `1px solid ${achieved ? '#065f46' : inRange ? '#1e3a5f' : '#1e293b'}`,
              position: 'relative', overflow: 'hidden',
            }}>
              {/* 진행바 배경 */}
              <div style={{
                position: 'absolute', top: 0, left: 0, height: '100%',
                width: `${pct}%`, borderRadius: 12,
                background: achieved
                  ? 'rgba(16,185,129,0.08)'
                  : `rgba(${ms.color.slice(1).match(/../g).map(x=>parseInt(x,16)).join(',')},0.05)`,
                transition: 'width 0.8s ease',
              }} />

              <div style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 12 }}>
                {/* 아이콘 */}
                <div style={{
                  fontSize: 24, width: 40, height: 40,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  borderRadius: 10,
                  background: achieved ? 'rgba(16,185,129,0.15)' : 'rgba(255,255,255,0.04)',
                }}>
                  {achieved ? '✅' : ms.icon}
                </div>

                {/* 텍스트 */}
                <div style={{ flex: 1 }}>
                  <div style={{
                    fontSize: 13, fontWeight: 700,
                    color: achieved ? '#34d399' : '#e2e8f0',
                  }}>
                    {ms.label}
                  </div>
                  <div style={{ fontSize: 11, color: '#64748b', marginTop: 1 }}>
                    {ms.desc}
                  </div>
                </div>

                {/* 오른쪽 금액 + 상태 */}
                <div style={{ textAlign: 'right' }}>
                  <div style={{
                    fontSize: 14, fontWeight: 700,
                    color: achieved ? '#34d399' : '#475569',
                  }}>
                    {ms.amount}만원
                  </div>
                  <div style={{ fontSize: 10, marginTop: 2 }}>
                    {achieved
                      ? <span style={{ color: '#34d399' }}>달성 ✓</span>
                      : <span style={{ color: '#64748b' }}>
                          {(ms.amount - currentMonthly).toFixed(1)}만원 부족
                        </span>
                    }
                  </div>
                </div>
              </div>

              {/* 진행률 바 */}
              {!achieved && (
                <div style={{ marginTop: 8, height: 3, background: '#1e293b', borderRadius: 2 }}>
                  <div style={{
                    height: '100%', borderRadius: 2,
                    width: `${pct}%`,
                    background: ms.color,
                    transition: 'width 0.8s ease',
                  }} />
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* FIRE 달성 예상 */}
      {fire_plan?.earliest_fire_age && (
        <div style={{
          marginTop: 14, padding: '10px 14px',
          background: '#1e293b', borderRadius: 10,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 11, color: '#64748b' }}>FIRE 최조 달성 예상</div>
            <div style={{ fontSize: 13, color: '#fbbf24', fontWeight: 700, marginTop: 2 }}>
              {fire_plan.earliest_fire_type} — 만 {fire_plan.earliest_fire_age}세
            </div>
          </div>
          <div style={{ fontSize: 24 }}>🏝️</div>
        </div>
      )}
    </div>
  )
}
