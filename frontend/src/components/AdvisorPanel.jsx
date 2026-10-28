/**
 * AdvisorPanel — AI Portfolio Advisor 패널
 *
 * 사용법:
 *   <AdvisorPanel portfolio={result} />
 *
 * 동작:
 *   "AI 분석 요청" 버튼 클릭 → POST /api/portfolio/advisor
 *   → {summary, strengths, risks, action_items, caveats, source} 표시
 *
 * 설계 원칙:
 *   - 자동 호출 X (사용자 명시적 요청 시에만)
 *   - Ollama 미실행 시 fallback 결과 자동 표시 (오류 X)
 *   - source="llm" vs "fallback" 구분 배지 표시
 *   - LLM이 종목/수치를 임의 생성하지 못하도록 백엔드에서 제약
 */
import { useState } from 'react'
import api from '../api/client'

const C = {
  cardBg:     'var(--surface)',
  cardBorder: 'var(--border)',
  text:       'var(--text)',
  muted:      'var(--text-sub)',
  green:      '#10b981',
  blue:       '#3b82f6',
  amber:      '#f59e0b',
  red:        '#ef4444',
  purple:     '#a855f7',
}

// ── 섹션 카드 ────────────────────────────────────────────────────
function SectionCard({ icon, title, items, color, bulletStyle = 'disc' }) {
  if (!items?.length) return null
  return (
    <div style={{
      background: `${color}0d`, border: `1px solid ${color}30`,
      borderRadius: 12, padding: '14px 16px', flex: 1, minWidth: 220,
    }}>
      <div style={{ fontSize: 12, color, fontWeight: 700, marginBottom: 10 }}>
        {icon} {title}
      </div>
      <ul style={{ margin: 0, paddingLeft: 18, listStyleType: bulletStyle }}>
        {items.map((item, i) => (
          <li key={i} style={{ fontSize: 12, color: C.text, marginBottom: 5, lineHeight: 1.6 }}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}

// ── 소스 배지 ────────────────────────────────────────────────────
function SourceBadge({ source, model }) {
  const isLLM = source === 'llm'
  return (
    <span style={{
      fontSize: 10, padding: '2px 8px', borderRadius: 6,
      background: isLLM ? `${C.purple}20` : `${C.muted}20`,
      color:      isLLM ? C.purple        : C.muted,
      border:     `1px solid ${isLLM ? C.purple + '40' : C.cardBorder}`,
    }}>
      {isLLM ? `${model || 'qwen3:14b'}` : '기본 분석'}
    </span>
  )
}

// ── 메인 컴포넌트 ────────────────────────────────────────────────
export default function AdvisorPanel({ portfolio }) {
  const [advice,  setAdvice]  = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const handleRequest = () => {
    if (!portfolio) return
    setLoading(true)
    setError(null)

    api.post('/api/portfolio/advisor', {
      portfolio,
      use_llm: true,
    }, { timeout: 120000 })
      .then(res  => setAdvice(res.data))
      .catch(err => {
        console.error('AdvisorPanel error:', err)
        setError('분석 요청에 실패했습니다. 잠시 후 다시 시도해주세요.')
      })
      .finally(() => setLoading(false))
  }

  if (!portfolio?.recommendations?.length) return null

  return (
    <div style={{ width: '100%', color: C.text }}>

      {/* ── 헤더 ── */}
      <div style={{
        display: 'flex', alignItems: 'center',
        justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 10,
      }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700 }}>AI Portfolio Advisor</div>
          <div style={{ fontSize: 13, color: C.text, marginTop: 2 }}>
            계산 완료된 분석 결과를 AI가 해석합니다
          </div>
        </div>

        {/* 분석 요청 버튼 */}
        {!advice && !loading && (
          <button
            onClick={handleRequest}
            style={{
              padding: '10px 20px', background: C.purple,
              border: 'none', borderRadius: 10, color: '#fff',
              fontSize: 13, fontWeight: 700, cursor: 'pointer',
              boxShadow: `0 0 12px ${C.purple}50`,
            }}
          >
            AI 분석 요청
          </button>
        )}

        {/* 다시 분석 버튼 */}
        {advice && !loading && (
          <button
            onClick={handleRequest}
            style={{
              padding: '8px 16px', background: 'transparent',
              border: `1px solid ${C.cardBorder}`, borderRadius: 8,
              color: C.muted, fontSize: 12, cursor: 'pointer',
            }}
          >
            ↺ 다시 분석
          </button>
        )}
      </div>

      {/* ── 로딩 ── */}
      {loading && (
        <div style={{
          padding: '40px', textAlign: 'center', color: C.muted,
          background: C.cardBg, borderRadius: 14, border: `1px solid ${C.cardBorder}`,
        }}>
          <div style={{ fontSize: 24, marginBottom: 8 }}></div>
          <div style={{ fontSize: 13 }}>
            포트폴리오 계산 결과를 분석 중입니다...
          </div>
          <div style={{ fontSize: 11, marginTop: 4 }}>
            (Ollama 미실행 시 기본 분석으로 대체됩니다)
          </div>
        </div>
      )}

      {/* ── 에러 ── */}
      {error && (
        <div style={{
          padding: 16, color: C.red, fontSize: 12,
          background: C.cardBg, borderRadius: 14, border: `1px solid ${C.cardBorder}`,
        }}>
          {error}
        </div>
      )}

      {/* ── 분석 결과 ── */}
      {advice && !loading && (
        <div>
          {/* Summary 카드 */}
          <div style={{
            background: C.cardBg, border: `1px solid ${C.cardBorder}`,
            borderRadius: 14, padding: '18px 20px', marginBottom: 14,
          }}>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              alignItems: 'flex-start', marginBottom: 10, flexWrap: 'wrap', gap: 6,
            }}>
              <div style={{ fontSize: 12, color: C.muted }}>종합 요약</div>
              <SourceBadge source={advice.source} model={advice.model} />
            </div>
            <div style={{ fontSize: 13, lineHeight: 1.8, color: C.text }}>
              {advice.summary}
            </div>
          </div>

          {/* 강점 / 위험 / 행동 카드 (3열) */}
          <div style={{ display: 'flex', gap: 10, marginBottom: 12, flexWrap: 'wrap' }}>
            <SectionCard
              icon="" title="강점"
              items={advice.strengths}
              color={C.green}
            />
            <SectionCard
              icon="" title="위험 요소"
              items={advice.risks}
              color={C.red}
            />
            <SectionCard
              icon="" title="행동 우선순위"
              items={advice.action_items}
              color={C.blue}
            />
          </div>

          {/* 주의사항 (하단) */}
          {advice.caveats?.length > 0 && (
            <div style={{
              background: `${C.amber}0a`, border: `1px solid ${C.amber}25`,
              borderRadius: 10, padding: '10px 14px',
              fontSize: 11, color: C.muted, lineHeight: 1.7,
            }}>
              {advice.caveats.join(' | ')}
            </div>
          )}
        </div>
      )}

      {/* ── 미클릭 상태 안내 ── */}
      {!advice && !loading && !error && (
        <div style={{
          padding: '24px', textAlign: 'center', color: C.muted,
          background: `${C.purple}08`, borderRadius: 14,
          border: `1px dashed ${C.purple}30`,
        }}>
          <div style={{ fontSize: 20, marginBottom: 8 }}></div>
          <div style={{ fontSize: 12 }}>
            "AI 분석 요청" 버튼을 클릭하면<br />
            계산 완료된 결과를 해석해 맞춤 조언을 제공합니다 (로컬 LLM 연결 시 AI 문장 추가, 미연결 시 기본 분석)
          </div>
        </div>
      )}

    </div>
  )
}
