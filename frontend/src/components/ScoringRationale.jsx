/**
 * ScoringRationale
 * ─────────────────────────────────────────────────────────────────
 * "점수 산정 기준 ⓘ" 접이식 패널 — 5축 표 + 성장 점수 기준 + 종합 커트라인 + disclaimer
 *
 * Props:
 *   scoringRationale — result.portfolio_health.scoring_rationale
 *   (SCORING_RATIONALE 딕셔너리 전체, API에서 그대로 전달)
 */
import { useState } from 'react'

const AXES = [
  { key: 'stability',       label: 'Stability',       score: 25, desc: '배당 안정성 · ML 위험 · Trap 탐지' },
  { key: 'growth',          label: 'Growth',           score: 20, desc: '포트폴리오 배당성장률(CAGR)' },
  { key: 'cashflow',        label: 'Cashflow',         score: 20, desc: '월배당 비중 · 현금흐름 다각화' },
  { key: 'tax_efficiency',  label: 'Tax Efficiency',   score: 20, desc: 'ISA/연금 활용 · 실효세율' },
  { key: 'diversification', label: 'Diversification',  score: 15, desc: '자산클래스 분산 · 집중 페널티' },
]

export default function ScoringRationale({ scoringRationale }) {
  const [open, setOpen] = useState(false)

  const health = scoringRationale?.health_grade_threshold || {}
  const growth = scoringRationale?.growth_score || {}
  const cutoff = scoringRationale?.overall_score_cutoff || {}

  const C = {
    border:   'var(--border, #dfe3ea)',
    text:     'var(--text, #1f2733)',
    sub:      'var(--text-sub, #5b6577)',
    accent:   '#2563eb',
    surface2: 'var(--surface2, #f8fafc)',
    amber:    '#d97706',
    amberBg:  'rgba(217,119,6,.06)',
  }

  return (
    <div style={{ marginTop: 8 }}>
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
          background: 'rgba(37,99,235,.07)', border: '1px solid rgba(37,99,235,.3)',
          color: C.accent, fontSize: 12, fontWeight: 600,
        }}
      >
        점수 산정 기준 ⓘ
        <span style={{ fontSize: 10, opacity: .7 }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div style={{
          marginTop: 8, padding: '14px 16px',
          background: 'var(--surface, #fff)',
          border: `1px solid ${C.border}`, borderRadius: 10, fontSize: 12.5,
        }}>

          {/* ① 5축 평가 구성 */}
          <SectionHeader icon="" title="평가 구성 (100점 만점)" />
          <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 14 }}>
            <thead>
              <tr style={{ background: C.surface2 }}>
                {['평가축', '배점', '핵심 기준'].map(h => (
                  <th key={h} style={{
                    padding: '6px 8px', textAlign: 'left',
                    fontSize: 11, fontWeight: 700, color: C.sub,
                    border: `1px solid ${C.border}`,
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {AXES.map(ax => (
                <tr key={ax.key}>
                  <td style={{ padding: '6px 8px', border: `1px solid ${C.border}`,
                    fontWeight: 600, color: C.text, fontSize: 12 }}>
                    {ax.label}
                  </td>
                  <td style={{ padding: '6px 8px', border: `1px solid ${C.border}`,
                    textAlign: 'center', fontWeight: 700, color: C.accent, fontSize: 13 }}>
                    {ax.score}점
                  </td>
                  <td style={{ padding: '6px 8px', border: `1px solid ${C.border}`,
                    color: C.sub, fontSize: 11.5 }}>
                    {ax.desc}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {/* ② 건강도 등급 기준 */}
          {health.thresholds && Object.keys(health.thresholds).length > 0 && (
            <>
              <SectionHeader icon="" title="건강도 등급 기준" />
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
                {Object.entries(health.thresholds).map(([range, label]) => (
                  <span key={range} style={{
                    padding: '3px 8px', borderRadius: 20, fontSize: 11,
                    background: C.surface2, border: `1px solid ${C.border}`,
                    color: C.text,
                  }}>
                    {range} → {label}
                  </span>
                ))}
              </div>
            </>
          )}

          {/* ③ 성장 점수 기준 */}
          {growth.thresholds && Object.keys(growth.thresholds).length > 0 && (
            <>
              <SectionHeader icon="" title="성장 점수 기준 (Growth · 20점 만점)" />
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 6 }}>
                {Object.entries(growth.thresholds).map(([range, label]) => (
                  <span key={range} style={{
                    padding: '3px 8px', borderRadius: 20, fontSize: 11,
                    background: C.surface2, border: `1px solid ${C.border}`,
                    color: C.text,
                  }}>
                    {range} → {label}
                  </span>
                ))}
              </div>
              {growth.internal_value_note && (
                <InternalNote note={growth.internal_value_note} C={C} />
              )}
            </>
          )}

          {/* ④ 종합 점수 후보 기준 */}
          {cutoff.description && (
            <>
              <SectionHeader icon="" title="종목 선별 기준" />
              <div style={{
                padding: '8px 10px', borderRadius: 7, marginBottom: 6,
                background: C.surface2, border: `1px solid ${C.border}`,
                color: C.text, fontSize: 12, lineHeight: 1.6,
              }}>
                {cutoff.description}
              </div>
              {cutoff.internal_design && (
                <p style={{ margin: '0 0 6px', fontSize: 11.5, color: C.sub, lineHeight: 1.5 }}>
                  {cutoff.internal_design}
                </p>
              )}
              {cutoff.internal_value_note && (
                <InternalNote note={cutoff.internal_value_note} C={C} />
              )}
            </>
          )}

          {/* disclaimer */}
          <p style={{
            margin: '12px 0 0', fontSize: 11.5, color: C.sub, lineHeight: 1.5,
            padding: '7px 10px', borderRadius: 6,
            background: 'rgba(100,116,139,.07)',
            borderLeft: '3px solid var(--border)',
          }}>
            각 평가축은 CFA·Vanguard·Morningstar 등 외부 금융 연구를 참고하여 설계했으며,
            세부 threshold와 cutoff는 시스템 내부 기준입니다. 향후 백테스트 기반 calibration 예정.
          </p>

        </div>
      )}
    </div>
  )
}

function SectionHeader({ icon, title }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 700, color: 'var(--text-sub, #5b6577)',
      textTransform: 'uppercase', letterSpacing: '.5px',
      marginBottom: 8, display: 'flex', alignItems: 'center', gap: 5,
    }}>
      {icon} {title}
    </div>
  )
}

function InternalNote({ note, C }) {
  return (
    <p style={{
      margin: '0 0 14px', fontSize: 11.5, color: C.sub, lineHeight: 1.5,
      padding: '6px 9px', borderRadius: 6,
      background: C.amberBg,
      borderLeft: `3px solid ${C.amber}`,
    }}>
      {note}
    </p>
  )
}
