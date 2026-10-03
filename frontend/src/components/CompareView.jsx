/**
 * CompareView — 두 포트폴리오 나란히 비교
 *
 * 사용법:
 *   <CompareView portfolio={result} />
 *
 * 동작:
 *   - 사용자가 A/B 파라미터를 입력
 *   - "비교 분석" 버튼 클릭 → POST /api/portfolio/compare
 *   - 레이더 차트 2개 + 핵심 지표 비교 테이블 표시
 *
 * 설계 원칙:
 *   - 현재 포트폴리오(A)는 portfolio prop에서 input을 가져와 기본값으로 채움
 *   - B는 사용자가 직접 입력 (나이, 투자금, 월적립금, 리스크 성향만 조절)
 *   - 자동 호출 X — 사용자 요청 시에만 실행 (서버 부하)
 */
import { useState } from 'react'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Legend,
} from 'recharts'
import api from '../api/client'

// ── 색상 팔레트 ──────────────────────────────────────────────────
const C = {
  bg:        'var(--surface)',
  cardBg:    'var(--surface)',
  border:    'var(--border)',
  text:      'var(--text)',
  muted:     'var(--text-sub)',
  green:     '#10b981',
  red:       '#ef4444',
  amber:     '#f59e0b',
  blue:      '#3b82f6',
  purple:    '#a855f7',
  colorA:    '#6366f1',   // 포트폴리오 A — 인디고
  colorB:    '#f97316',   // 포트폴리오 B — 오렌지
}

// ── 레이더 축 레이블 매핑 ────────────────────────────────────────
const RADAR_LABELS = {
  stability:          '안정성',
  growth:             '성장',
  cashflow:           '현금흐름',
  cashflow_smooth:    '균등성',
  inflation_defense:  '물가방어',
  tax_efficiency:     '세금효율',
  diversification:    '분산도',
}

// ── 리스크 성향 옵션 ─────────────────────────────────────────────
const RISK_OPTIONS = [
  { value: 'conservative', label: '보수형' },
  { value: 'moderate',     label: '중립형' },
  { value: 'aggressive',   label: '공격형' },
]

const ARCHETYPE_OPTIONS = [
  { value: '혼합형', label: '혼합형' },
  { value: '성장형', label: '성장형' },
  { value: '월배당형', label: '월배당형' },
  { value: '안정형', label: '안정형' },
  { value: '은퇴형', label: '은퇴형' },
]

// ── 레이더 차트 ──────────────────────────────────────────────────
function PortRadar({ label, color, radarData }) {
  if (!radarData?.length) return (
    <div style={{
      flex: 1, minWidth: 260, padding: 20, textAlign: 'center',
      color: C.muted, fontSize: 12,
    }}>
      데이터 없음
    </div>
  )

  const data = radarData.map(d => ({
    axis:  RADAR_LABELS[d.axis] || d.axis,
    score: d.pct,
    max:   100,
  }))

  return (
    <div style={{
      flex: 1, minWidth: 260,
      background: C.cardBg, border: `1px solid ${color}40`,
      borderRadius: 14, padding: '16px 12px',
    }}>
      <div style={{
        fontSize: 12, fontWeight: 700, color,
        marginBottom: 10, textAlign: 'center',
      }}>
        {label}
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <RadarChart data={data}>
          <PolarGrid stroke={C.border} />
          <PolarAngleAxis
            dataKey="axis"
            tick={{ fill: C.muted, fontSize: 10 }}
          />
          <PolarRadiusAxis
            angle={90} domain={[0, 100]}
            tick={{ fill: C.muted, fontSize: 8 }}
          />
          <Radar
            name={label}
            dataKey="score"
            stroke={color}
            fill={color}
            fillOpacity={0.2}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── 비교 지표 행 ─────────────────────────────────────────────────
function MetricRow({ metric }) {
  const { label, a, b, unit, winner } = metric
  const va = typeof a === 'number' ? a : 0
  const vb = typeof b === 'number' ? b : 0
  const fmt = v => {
    if (Math.abs(v) >= 1000) return v.toLocaleString('ko-KR', { maximumFractionDigits: 0 })
    return String(Number(v.toFixed(1)))
  }

  const winA = winner === 'a'
  const winB = winner === 'b'

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '1fr auto 1fr',
      alignItems: 'center', gap: 8,
      padding: '7px 0',
      borderBottom: `1px solid ${C.border}30`,
    }}>
      {/* A 값 */}
      <div style={{
        textAlign: 'right', fontSize: 13, fontWeight: winA ? 700 : 400,
        color: winA ? C.colorA : C.muted,
        display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4,
      }}>
        {winA && <span style={{ fontSize: 10 }}>▲</span>}
        {fmt(va)}{unit}
      </div>

      {/* 라벨 */}
      <div style={{
        textAlign: 'center', fontSize: 11, color: C.muted,
        minWidth: 110, lineHeight: 1.4,
      }}>
        {label}
      </div>

      {/* B 값 */}
      <div style={{
        textAlign: 'left', fontSize: 13, fontWeight: winB ? 700 : 400,
        color: winB ? C.colorB : C.muted,
        display: 'flex', alignItems: 'center', gap: 4,
      }}>
        {fmt(vb)}{unit}
        {winB && <span style={{ fontSize: 10 }}>▲</span>}
      </div>
    </div>
  )
}

// ── 스코어 카드 ──────────────────────────────────────────────────
function ScoreCard({ label, count, color }) {
  return (
    <div style={{
      flex: 1, textAlign: 'center', padding: '10px 8px',
      background: `${color}12`, border: `1px solid ${color}30`,
      borderRadius: 10,
    }}>
      <div style={{ fontSize: 22, fontWeight: 800, color }}>{count}</div>
      <div style={{ fontSize: 11, color: C.muted, marginTop: 2 }}>{label}</div>
    </div>
  )
}

// ── 입력 필드 ────────────────────────────────────────────────────
function Field({ label, value, onChange, type = 'number', min, max, step = 1 }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{ fontSize: 11, color: C.muted, display: 'block', marginBottom: 3 }}>
        {label}
      </label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(type === 'number' ? Number(e.target.value) : e.target.value)}
        min={min} max={max} step={step}
        style={{
          width: '100%', background: 'var(--surface)', border: `1px solid ${C.border}`,
          borderRadius: 8, padding: '7px 10px', color: C.text,
          fontSize: 13, boxSizing: 'border-box',
        }}
      />
    </div>
  )
}

function Select({ label, value, onChange, options }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <label style={{ fontSize: 11, color: C.muted, display: 'block', marginBottom: 3 }}>
        {label}
      </label>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        style={{
          width: '100%', background: 'var(--surface)', border: `1px solid ${C.border}`,
          borderRadius: 8, padding: '7px 10px', color: C.text,
          fontSize: 13, boxSizing: 'border-box',
        }}
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

// ── 메인 컴포넌트 ────────────────────────────────────────────────
export default function CompareView({ portfolio }) {
  const inp = portfolio?.input || {}

  // A = 현재 포트폴리오 설정 (기본값)
  const [formA, setFormA] = useState({
    age:               inp.age               || 40,
    annual_income:     inp.annual_income     || 5000,
    monthly_target:    inp.monthly_target    || 100,
    investable_amount: inp.investable        || inp.investable_amount || 5000,
    risk_tolerance:    inp.risk_tolerance    || 'moderate',
    archetype:         inp.archetype         || '혼합형',
    monthly_savings:   inp.monthly_savings   || 50,
    target_fire_age:   inp.target_fire_age   || 55,
  })

  // B = 비교 포트폴리오 설정 (기본값은 A와 다르게)
  const [formB, setFormB] = useState({
    age:               inp.age               || 40,
    annual_income:     inp.annual_income     || 5000,
    monthly_target:    inp.monthly_target    || 100,
    investable_amount: (inp.investable || inp.investable_amount || 5000) + 2000,
    risk_tolerance:    'aggressive',
    archetype:         '성장형',
    monthly_savings:   (inp.monthly_savings || 50) + 20,
    target_fire_age:   (inp.target_fire_age || 55) - 5,
  })

  const [result,  setResult]  = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const updA = k => v => setFormA(prev => ({ ...prev, [k]: v }))
  const updB = k => v => setFormB(prev => ({ ...prev, [k]: v }))

  const handleCompare = () => {
    setLoading(true)
    setError(null)
    api.post('/api/portfolio/compare', { req_a: formA, req_b: formB })
      .then(res  => setResult(res.data))
      .catch(err => {
        console.error('CompareView error:', err)
        setError('비교 분석 중 오류가 발생했습니다. 잠시 후 다시 시도하세요.')
      })
      .finally(() => setLoading(false))
  }

  if (!portfolio?.recommendations?.length) return null

  // 레이더 데이터 추출
  const radarA = result?.portfolio_a?.portfolio_health?.radar_data || []
  const radarB = result?.portfolio_b?.portfolio_health?.radar_data || []
  const metrics = result?.comparison?.metrics || []
  const wc = result?.comparison?.winner_counts || { a: 0, b: 0, tie: 0 }

  const labelA = `포트폴리오 A (${formA.archetype})`
  const labelB = `포트폴리오 B (${formB.archetype})`

  return (
    <div style={{ width: '100%', color: C.text }}>

      {/* ── 헤더 ── */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 15, fontWeight: 700 }}>포트폴리오 비교</div>
        <div style={{ fontSize: 12, color: C.muted, marginTop: 2 }}>
          두 가지 포트폴리오 설정을 동시에 분석해 최적 전략을 선택합니다
        </div>
      </div>

      {/* ── 입력 패널 ── */}
      <div style={{
        display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap',
      }}>
        {/* A 패널 */}
        {[
          { form: formA, upd: updA, label: labelA, color: C.colorA },
          { form: formB, upd: updB, label: labelB, color: C.colorB },
        ].map(({ form, upd, label, color }) => (
          <div key={label} style={{
            flex: 1, minWidth: 240,
            background: C.cardBg, border: `1px solid ${color}40`,
            borderRadius: 14, padding: '14px 16px',
          }}>
            <div style={{ fontSize: 12, fontWeight: 700, color, marginBottom: 12 }}>
              {label}
            </div>
            <Field label="나이" value={form.age} onChange={upd('age')} min={20} max={80} />
            <Field label="투자금 (만원)" value={form.investable_amount} onChange={upd('investable_amount')} min={0} max={100000} step={500} />
            <Field label="월 적립금 (만원)" value={form.monthly_savings} onChange={upd('monthly_savings')} min={0} max={1000} step={10} />
            <Field label="목표 월배당 (만원)" value={form.monthly_target} onChange={upd('monthly_target')} min={0} max={1000} step={10} />
            <Field label="목표 FIRE 나이" value={form.target_fire_age} onChange={upd('target_fire_age')} min={30} max={80} />
            <Select label="리스크 성향" value={form.risk_tolerance} onChange={upd('risk_tolerance')} options={RISK_OPTIONS} />
            <Select label="아키타입" value={form.archetype} onChange={upd('archetype')} options={ARCHETYPE_OPTIONS} />
          </div>
        ))}
      </div>

      {/* ── 비교 실행 버튼 ── */}
      <div style={{ textAlign: 'center', marginBottom: 20 }}>
        <button
          onClick={handleCompare}
          disabled={loading}
          style={{
            padding: '12px 32px',
            background: loading ? C.border : `linear-gradient(135deg, ${C.colorA}, ${C.colorB})`,
            border: 'none', borderRadius: 12, color: '#fff',
            fontSize: 14, fontWeight: 700, cursor: loading ? 'default' : 'pointer',
            boxShadow: loading ? 'none' : `0 0 20px ${C.colorA}40`,
            transition: 'all 0.2s',
          }}
        >
          {loading ? '분석 중...' : '⚖️ 비교 분석 실행'}
        </button>
        {!result && !loading && (
          <div style={{ fontSize: 11, color: C.muted, marginTop: 8 }}>
            파이프라인 2회 실행 — 약 30~60초 소요
          </div>
        )}
      </div>

      {/* ── 에러 ── */}
      {error && (
        <div style={{
          padding: 14, color: C.red, fontSize: 12,
          background: C.cardBg, borderRadius: 12, border: `1px solid ${C.border}`,
          marginBottom: 16,
        }}>
          {error}
        </div>
      )}

      {/* ── 결과 ── */}
      {result && !loading && (
        <>
          {/* 레이더 차트 2개 */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
            <PortRadar label={labelA} color={C.colorA} radarData={radarA} />
            <PortRadar label={labelB} color={C.colorB} radarData={radarB} />
          </div>

          {/* 승패 요약 카드 */}
          <div style={{
            display: 'flex', gap: 10, marginBottom: 16,
          }}>
            <ScoreCard label={`${labelA} 우세`} count={wc.a} color={C.colorA} />
            <ScoreCard label="무승부" count={wc.tie} color={C.muted} />
            <ScoreCard label={`${labelB} 우세`} count={wc.b} color={C.colorB} />
          </div>

          {/* 지표 비교 테이블 */}
          <div style={{
            background: C.cardBg, border: `1px solid ${C.border}`,
            borderRadius: 14, padding: '14px 18px',
          }}>
            {/* 테이블 헤더 */}
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr auto 1fr',
              gap: 8, marginBottom: 8, paddingBottom: 8,
              borderBottom: `1px solid ${C.border}`,
            }}>
              <div style={{ textAlign: 'right', fontSize: 11, fontWeight: 700, color: C.colorA }}>
                포트폴리오 A
              </div>
              <div style={{ textAlign: 'center', fontSize: 11, color: C.muted, minWidth: 110 }}>
                지표
              </div>
              <div style={{ textAlign: 'left', fontSize: 11, fontWeight: 700, color: C.colorB }}>
                포트폴리오 B
              </div>
            </div>

            {metrics.map(m => (
              <MetricRow key={m.key} metric={m} />
            ))}
          </div>

          {/* 종합 의견 */}
          <div style={{
            marginTop: 12, padding: '10px 14px', fontSize: 12,
            background: `${C.amber}0a`, border: `1px solid ${C.amber}25`,
            borderRadius: 10, color: C.muted, lineHeight: 1.7,
          }}>
            {wc.a > wc.b
              ? `⚡ 포트폴리오 A가 ${wc.a}개 지표에서 우세합니다. 현재 전략을 유지하거나 소폭 조정하세요.`
              : wc.b > wc.a
              ? `⚡ 포트폴리오 B가 ${wc.b}개 지표에서 우세합니다. B 전략으로의 전환을 검토해보세요.`
              : `⚡ A와 B가 각각 ${wc.a}개 지표에서 동등합니다. 개인 목표 우선순위에 따라 선택하세요.`
            }
          </div>
        </>
      )}

    </div>
  )
}
