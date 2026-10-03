/**
 * DividendCalendarHeatmap — 월별 배당 히트맵
 *
 * 왜 히트맵인가?
 *   "내가 이번 달 배당이 얼마나 들어오나"를 달력 형태로 보여주면
 *   배당 공백 월(dry month)을 직관적으로 파악할 수 있다.
 *   숫자 표보다 훨씬 강한 UX 임팩트.
 *
 * 핵심 기능:
 *   - 월별 예상 배당금 색상 강도로 표현
 *   - dry month (배당 없는 달) 명시적으로 표시
 *   - hover 시 해당 월 종목 목록 + 금액 표시
 *   - 연간 총 배당 + 월평균 통계 표시
 */
import { useState } from 'react'

const MONTH_LABELS = ['1월','2월','3월','4월','5월','6월','7월','8월','9월','10월','11월','12월']

function getHeatColor(amount, maxAmount) {
  if (!amount || amount <= 0) return { bg: '#ffffff', text: '#c8d0dc', isDry: true }
  const ratio = Math.min(amount / maxAmount, 1)
  if (ratio >= 0.8) return { bg: '#065f46', text: '#059669', isDry: false }
  if (ratio >= 0.6) return { bg: '#064e3b', text: '#6ee7b7', isDry: false }
  if (ratio >= 0.4) return { bg: '#1e3a2f', text: '#86efac', isDry: false }
  if (ratio >= 0.2) return { bg: '#1a2e23', text: '#bbf7d0', isDry: false }
  return { bg: '#132018', text: '#d1fae5', isDry: false }
}

export default function DividendCalendarHeatmap({ calendar }) {
  const [hovered, setHovered] = useState(null)

  if (!calendar?.monthly_summary) return null

  const monthly = calendar.monthly_summary   // {1: {amount, tickers: [...]}, ...}
  const amounts = Object.values(monthly).map(m => m?.amount_만원 || m?.amount || 0)
  const maxAmount = Math.max(...amounts, 1)
  const totalAnnual = amounts.reduce((a, b) => a + b, 0)
  const avgMonthly  = totalAnnual / 12
  const dryMonths   = amounts.filter(a => a <= 0).length

  return (
    <div style={{
      background: '#ffffff', borderRadius: 16, padding: '20px 24px',
      border: '1px solid #dfe3ea',
    }}>
      {/* 헤더 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: '#283143' }}>
            배당 캘린더
          </div>
          <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
            월별 예상 배당 현금흐름
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 11, color: '#64748b' }}>연간 합계</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: '#059669' }}>
            {totalAnnual.toFixed(1)}만원
          </div>
        </div>
      </div>

      {/* 히트맵 그리드 */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
        gap: 8,
      }}>
        {MONTH_LABELS.map((label, i) => {
          const monthNum = i + 1
          const data     = monthly[monthNum] || monthly[String(monthNum)] || {}
          const amount   = data.amount_만원 || data.amount || 0
          const tickers  = data.tickers || data.stocks || []
          const { bg, text, isDry } = getHeatColor(amount, maxAmount)
          const isHovered = hovered === monthNum

          return (
            <div
              key={monthNum}
              style={{
                background:    isHovered ? '#1e3a5f' : bg,
                borderRadius:  10,
                padding:       '10px 12px',
                cursor:        'pointer',
                border:        `1px solid ${isHovered ? '#3b82f6' : isDry ? '#dfe3ea' : '#1e3a2f'}`,
                transition:    'all 0.2s',
                position:      'relative',
              }}
              onMouseEnter={() => setHovered(monthNum)}
              onMouseLeave={() => setHovered(null)}
            >
              <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>{label}</div>
              {isDry ? (
                <div style={{ fontSize: 13, color: '#c8d0dc', fontWeight: 600 }}>—</div>
              ) : (
                <div style={{ fontSize: 15, fontWeight: 700, color: text }}>
                  {amount.toFixed(1)}만
                </div>
              )}

              {/* 호버 시 종목 목록 */}
              {isHovered && tickers.length > 0 && (
                <div style={{
                  position: 'absolute', bottom: '100%', left: 0, zIndex: 50,
                  background: '#dfe3ea', borderRadius: 8,
                  padding: '8px 10px', minWidth: 140,
                  border: '1px solid #c8d0dc', marginBottom: 4,
                  boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
                }}>
                  <div style={{ fontSize: 11, color: '#64748b', marginBottom: 4 }}>
                    {label} 배당 종목
                  </div>
                  {tickers.slice(0, 5).map((t, j) => (
                    <div key={j} style={{ fontSize: 11, color: 'var(--text-sub)', marginTop: 2 }}>
                      {typeof t === 'string' ? t : (t.ticker || t.name || t)}
                    </div>
                  ))}
                  {tickers.length > 5 && (
                    <div style={{ fontSize: 10, color: '#475569', marginTop: 2 }}>
                      +{tickers.length - 5}개 더
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* 하단 통계 */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
        gap: 8, marginTop: 14,
      }}>
        {[
          { label: '월 평균', value: `${avgMonthly.toFixed(1)}만원`, color: '#059669' },
          { label: '배당 없는 달', value: `${dryMonths}개월`, color: dryMonths >= 3 ? '#ef4444' : dryMonths >= 1 ? '#d97706' : '#059669' },
          { label: '배당 있는 달', value: `${12 - dryMonths}개월`, color: '#6366f1' },
        ].map(stat => (
          <div key={stat.label} style={{
            background: '#dfe3ea', borderRadius: 8, padding: '8px 12px', textAlign: 'center',
          }}>
            <div style={{ fontSize: 10, color: '#64748b' }}>{stat.label}</div>
            <div style={{ fontSize: 14, fontWeight: 700, color: stat.color, marginTop: 2 }}>
              {stat.value}
            </div>
          </div>
        ))}
      </div>

      {/* dry month 경고 */}
      {dryMonths >= 2 && (
        <div style={{
          marginTop: 12, padding: '8px 12px',
          background: '#1c1917', borderRadius: 8,
          border: '1px solid #78350f', fontSize: 12, color: '#d97706',
        }}>
          ⚠️ 배당 공백 {dryMonths}개월 — 월배당 ETF(JEPI·JEPQ) 추가 편입으로 균등화 권장
        </div>
      )}
    </div>
  )
}
