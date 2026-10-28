/**
 * StockRationaleCard — 종목별 추천 근거 접이식 패널
 *
 * Props:
 *   rec  — recommendations 배열의 개별 항목 (전체 필드 포함)
 *
 * 표시 내용:
 *   1. recommendation_reason / description — 추천 이유 텍스트
 *   2. 핵심 지표 (수익률, 변동성, 배당성장률, MDD)
 *   3. KR 서브스코어 바 (kr_score_breakdown 있을 때만)
 *   4. 주의사항 — trap_level, ml_status, P_BROKEN/P_WEAKENING, dps_cuts_3y
 */

import { useState } from 'react'

// ── 색상 ──────────────────────────────────────────────────────
const C = {
  ok:     '#10b981',
  warn:   '#f59e0b',
  danger: '#ef4444',
  blue:   '#2563eb',
  purple: '#7c3aed',
  muted:  'var(--text-sub)',
  text:   'var(--text)',
  border: 'var(--border)',
  bg:     'var(--surface)',
  bg2:    'var(--surface2)',
}

// ── 서브스코어 바 ─────────────────────────────────────────────
function ScoreBar({ label, value, max, color }) {
  const pct = Math.min(100, max > 0 ? (value / max) * 100 : 0)
  return (
    <div style={{ marginBottom: 7 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between',
                    fontSize: 11, color: C.muted, marginBottom: 3 }}>
        <span>{label}</span>
        <span style={{ fontWeight: 600, color: C.text }}>
          {value.toFixed(0)} / {max}
        </span>
      </div>
      <div style={{
        height: 6, borderRadius: 3,
        background: 'var(--border)',
        overflow: 'hidden',
      }}>
        <div style={{
          height: '100%', borderRadius: 3,
          width: `${pct}%`,
          background: color,
          transition: 'width .3s ease',
        }} />
      </div>
    </div>
  )
}

// ── 주의사항 배지 ─────────────────────────────────────────────
function CautionBadge({ icon, text, color }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      padding: '3px 8px', borderRadius: 6, fontSize: 11, fontWeight: 600,
      background: `${color}18`,
      border: `1px solid ${color}40`,
      color,
    }}>
      {icon} {text}
    </span>
  )
}

// ── 지표 칩 ──────────────────────────────────────────────────
function MetricChip({ label, value, color }) {
  return (
    <div style={{
      background: C.bg2, border: `1px solid ${C.border}`,
      borderRadius: 8, padding: '6px 10px', minWidth: 80,
    }}>
      <div style={{ fontSize: 10, color: C.muted, marginBottom: 2 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color: color || C.text }}>{value}</div>
    </div>
  )
}

// ── 메인 컴포넌트 ─────────────────────────────────────────────
export default function StockRationaleCard({ rec }) {
  const [open, setOpen] = useState(false)

  if (!rec) return null

  const reason = rec.recommendation_reason || rec.description || '추천 근거 없음'
  const bd     = rec.kr_score_breakdown    // KR 전용 서브스코어 (없으면 undefined)
  const dy     = rec.dividend_yield        ?? 0
  const vol    = rec.volatility_annual     ?? null
  const mdd    = rec.max_drawdown_pct      ?? null
  const dg     = rec.div_growth_rate_pct   ?? 0
  const cons   = rec.consecutive_years     ?? 0
  const ml     = rec.ml_status             ?? 'INTACT'
  const trap   = rec.trap_level            ?? 'SAFE'
  const pBrk   = rec.P_BROKEN             ?? 0
  const pWkn   = rec.P_WEAKENING          ?? 0
  const cuts   = rec.dps_cuts_3y          ?? 0
  const dpsYoy = rec.dps_yoy_pct          ?? null

  // ── 주의사항 생성 ──────────────────────────────────────────
  const cautions = []
  if (trap === 'YIELD_TRAP') {
    cautions.push({ icon: '', text: '고배당 함정 의심 — 지속 가능성 확인 필요', color: C.danger })
  } else if (trap === 'MODERATE') {
    cautions.push({ icon: '', text: '배당 지속성 주의', color: C.warn })
  }
  if (ml === 'BROKEN') {
    cautions.push({ icon: '', text: 'AI: 배당 위험 신호 (BROKEN)', color: C.danger })
  } else if (ml === 'WEAKENING') {
    cautions.push({ icon: '', text: 'AI: 배당 약화 신호 (WEAKENING)', color: C.warn })
  }
  if (pBrk > 0.3) {
    cautions.push({ icon: '', text: `배당컷 위험 지수 ${(pBrk * 100).toFixed(0)}%`, color: C.danger })
  } else if (pBrk > 0.15) {
    cautions.push({ icon: '', text: `배당컷 위험 지수 ${(pBrk * 100).toFixed(0)}%`, color: C.warn })
  }
  if (cuts > 0) {
    cautions.push({ icon: '', text: `최근 3년 배당 삭감 ${cuts}회`, color: C.warn })
  }
  if (rec.cold_start) {
    cautions.push({ icon: '', text: 'ML 분석 데이터 부족 — rule-based 대체', color: C.warn })
  }

  // ── 배당 성장 메시지 ──────────────────────────────────────
  const growthNote = dg > 7 ? `배당성장 ${dg.toFixed(1)}%/년 — 복리 효과 우수`
                   : dg > 4 ? `배당성장 ${dg.toFixed(1)}%/년 — 물가 초과`
                   : dg > 0 ? `배당성장 ${dg.toFixed(1)}%/년 — 완만`
                   : null

  // ── 연속 배당 연수 메시지 ──────────────────────────────────
  const consNote = cons >= 25 ? `배당귀족 (${cons}년 연속 성장)` : cons >= 10 ? `${cons}년 연속 배당` : null

  const fmtPct = (v) => v === null ? '—' : `${v >= 0 ? '' : ''}${v.toFixed(1)}%`

  return (
    <div style={{ marginTop: 6 }}>
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          padding: '3px 9px', borderRadius: 6, cursor: 'pointer',
          background: 'rgba(37,99,235,.07)',
          border: '1px solid rgba(37,99,235,.25)',
          color: C.blue, fontSize: 11.5, fontWeight: 600,
        }}
      >
        추천 근거 ⓘ
        {cautions.length > 0 && (
          <span style={{
            background: C.warn, color: '#fff',
            borderRadius: '50%', width: 14, height: 14,
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 9, fontWeight: 700,
          }}>
            {cautions.length}
          </span>
        )}
        <span style={{ fontSize: 10, opacity: .7 }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{
          marginTop: 6, padding: '12px 14px',
          background: C.bg, border: `1px solid ${C.border}`,
          borderRadius: 10, fontSize: 12,
        }}>

          {/* ① 추천 이유 텍스트 */}
          <div style={{
            fontSize: 12, color: C.text, lineHeight: 1.6,
            padding: '8px 10px', borderRadius: 7,
            background: 'rgba(37,99,235,.04)',
            border: '1px solid rgba(37,99,235,.1)',
            marginBottom: 12,
          }}>
            {reason}
          </div>

          {/* ② 핵심 지표 칩 */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
            <MetricChip
              label="배당수익률"
              value={`${dy.toFixed(1)}%`}
              color={dy >= 5 ? C.ok : dy >= 3 ? C.blue : C.muted}
            />
            {mdd !== null && (
              <MetricChip
                label="최대낙폭(MDD)"
                value={fmtPct(mdd)}
                color={Math.abs(mdd) <= 20 ? C.ok : Math.abs(mdd) <= 35 ? C.warn : C.danger}
              />
            )}
            {vol !== null && (
              <MetricChip
                label="연간 변동성"
                value={`${vol.toFixed(1)}%`}
                color={vol <= 15 ? C.ok : vol <= 25 ? C.warn : C.danger}
              />
            )}
            {dg > 0 && (
              <MetricChip label="배당성장률" value={`${dg.toFixed(1)}%`} color={dg >= 5 ? C.ok : C.warn} />
            )}
            {dpsYoy !== null && (
              <MetricChip
                label="최근 배당변화"
                value={`${dpsYoy >= 0 ? '+' : ''}${dpsYoy.toFixed(1)}%`}
                color={dpsYoy >= 0 ? C.ok : C.danger}
              />
            )}
          </div>

          {/* ③ 배당 지속 뱃지 */}
          {(growthNote || consNote) && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
              {growthNote && (
                <span style={{
                  fontSize: 11, padding: '3px 8px', borderRadius: 20,
                  background: 'rgba(16,185,129,.08)', border: '1px solid rgba(16,185,129,.25)',
                  color: C.ok,
                }}>✓ {growthNote}</span>
              )}
              {consNote && (
                <span style={{
                  fontSize: 11, padding: '3px 8px', borderRadius: 20,
                  background: 'rgba(37,99,235,.07)', border: '1px solid rgba(37,99,235,.2)',
                  color: C.blue,
                }}>{consNote}</span>
              )}
            </div>
          )}

          {/* ④ KR 서브스코어 바 */}
          {bd && (
            <div style={{
              padding: '10px 12px', borderRadius: 8, marginBottom: 12,
              background: C.bg2, border: `1px solid ${C.border}`,
            }}>
              <div style={{
                fontSize: 11, fontWeight: 700, color: C.muted,
                textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 8,
              }}>
                AI 점수 분석 (한국주식 전용)
              </div>
              <ScoreBar label="배당수익률 점수" value={bd.yield_score} max={35} color={C.blue}   />
              <ScoreBar label="배당 안정성"      value={bd.stability}   max={35} color={C.ok}     />
              <ScoreBar label="재무 건전성"      value={bd.financial}   max={20} color={C.purple} />
              <ScoreBar label="성장성"           value={bd.growth}      max={10} color={C.warn}   />
            </div>
          )}

          {/* ⑤ 주의사항 */}
          {cautions.length > 0 && (
            <div>
              <div style={{
                fontSize: 11, fontWeight: 700, color: C.muted,
                textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 6,
              }}>
                주의사항
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {cautions.map((c, i) => (
                  <CautionBadge key={i} icon={c.icon} text={c.text} color={c.color} />
                ))}
              </div>
            </div>
          )}

          {/* ML 면책 노트 */}
          {(ml === 'WEAKENING' || ml === 'BROKEN' || pBrk > 0.1) && (
            <p style={{
              margin: '10px 0 0', fontSize: 10.5, color: C.muted, lineHeight: 1.5,
              padding: '6px 9px', borderRadius: 6,
              background: 'rgba(100,116,139,.06)',
              borderLeft: '3px solid var(--border)',
            }}>
              ※ AI 위험 신호는 TabPFN Survival 모델의 미검증 위험 점수입니다.
              실제 배당 삭감을 확정하는 지표가 아닙니다. 참고용으로만 활용하세요.
            </p>
          )}

        </div>
      )}
    </div>
  )
}
