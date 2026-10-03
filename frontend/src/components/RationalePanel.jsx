/**
 * RationalePanel
 * ─────────────────────────────────────────────────────────────────
 * "추천 기준 ⓘ" 접이식 패널 — 아키타입 rationale를 3계층으로 표시
 *
 * Props:
 *   rationale  — result.archetype.rationale (ARCHETYPE_RATIONALE[archetype])
 *   label      — 아키타입 한글 레이블 (예: "🛡️ 안정형")
 */
import { useState } from 'react'

export default function RationalePanel({ rationale, label }) {
  const [open, setOpen] = useState(false)

  if (!rationale || !rationale.investment_goal) return null

  const ext = rationale.external_benchmark || {}
  const C = {
    bg:      'var(--surface, #ffffff)',
    border:  'var(--border, #dfe3ea)',
    text:    'var(--text, #1f2733)',
    sub:     'var(--text-sub, #5b6577)',
    accent:  '#2563eb',
    tagBg:   'rgba(37,99,235,.07)',
  }

  return (
    <div style={{ marginTop: 10 }}>
      {/* 토글 버튼 */}
      <button
        onClick={() => setOpen(v => !v)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          padding: '4px 10px', borderRadius: 6, cursor: 'pointer',
          background: C.tagBg, border: `1px solid ${C.accent}30`,
          color: C.accent, fontSize: 12, fontWeight: 600,
          transition: 'all .15s',
        }}
      >
        추천 기준 ⓘ
        <span style={{ fontSize: 10, opacity: .7 }}>{open ? '▲' : '▼'}</span>
      </button>

      {/* 접이식 본문 */}
      {open && (
        <div style={{
          marginTop: 8, padding: '14px 16px',
          background: C.bg, border: `1px solid ${C.border}`,
          borderRadius: 10, fontSize: 12.5,
        }}>

          {/* ① 투자 목적 */}
          <Section icon="🎯" title="투자 목적">
            <p style={{ margin: 0, color: C.text, lineHeight: 1.6 }}>
              {rationale.investment_goal}
            </p>
          </Section>

          {/* ② 외부 기준 */}
          {ext.source && (
            <Section icon="📚" title="외부 기준점">
              <div style={{
                padding: '8px 10px', borderRadius: 7,
                background: 'rgba(37,99,235,.04)',
                border: '1px solid rgba(37,99,235,.12)',
                marginBottom: 6,
              }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: C.accent }}>
                  {ext.source}
                </span>
              </div>
              <p style={{ margin: 0, color: C.sub, lineHeight: 1.6 }}>
                {ext.data}
              </p>
            </Section>
          )}

          {/* ③ 시스템 적용 + 내부값 안내 */}
          {(rationale.design_interpretation || rationale.internal_value_note) && (
            <Section icon="⚙️" title="시스템 적용">
              {rationale.design_interpretation && (
                <p style={{ margin: '0 0 6px', color: C.text, lineHeight: 1.6 }}>
                  {rationale.design_interpretation}
                </p>
              )}
              {rationale.internal_value_note && (
                <p style={{
                  margin: 0, fontSize: 11.5, color: C.sub, lineHeight: 1.5,
                  padding: '6px 9px', borderRadius: 6,
                  background: 'rgba(100,116,139,.07)',
                  borderLeft: '3px solid var(--border)',
                }}>
                  💡 {rationale.internal_value_note}
                </p>
              )}
            </Section>
          )}

        </div>
      )}
    </div>
  )
}

function Section({ icon, title, children }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: 'var(--text-sub, #5b6577)',
        textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 5,
        display: 'flex', alignItems: 'center', gap: 5,
      }}>
        {icon} {title}
      </div>
      {children}
    </div>
  )
}
