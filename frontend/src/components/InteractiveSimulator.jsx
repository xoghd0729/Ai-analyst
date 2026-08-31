/**
 * InteractiveSimulator — FIRE 역산 인터랙티브 시뮬레이터
 *
 * 사용법:
 *   <InteractiveSimulator portfolio={result} />
 *
 *   portfolio: POST /api/portfolio/recommend 응답 전체
 *   (초기 슬라이더 값, current_age, avg_net_yield 추출에 사용)
 *
 * 슬라이더 4개:
 *   ① 초기 투자금 (0 ~ 50,000만원)
 *   ② 월 적립금   (0 ~ 500만원)
 *   ③ 목표 월배당 (10 ~ 500만원)
 *   ④ 목표 FIRE 나이 (30 ~ 75세)
 *
 * 동작:
 *   슬라이더 변경 → debounce 300ms → POST /api/portfolio/fire-reverse
 *   로딩 중에는 이전 결과를 유지하고 작은 스피너만 표시 (UX 깔끔)
 *
 * 결과 표시:
 *   - 헤드라인: "55세 목표 → 현재 예상 60세 → 5년 부족"
 *   - 역산 3경로:
 *       Path 1: 월 적립금 +X만원이면 목표 달성
 *       Path 2: 초기자산 +Y만원이면 목표 달성
 *       Path 3: 현재 조건으로 최대 Z만원/월 달성 가능
 *   - 목표 이미 달성 시: 축하 배너
 */
import { useState, useEffect, useRef } from 'react'
import api from '../api/client'

// ── 색상 상수 ────────────────────────────────────────────────────
const C = {
  cardBg:     '#1e293b',
  cardBorder: '#334155',
  text:       '#e2e8f0',
  muted:      '#94a3b8',
  green:      '#10b981',
  blue:       '#3b82f6',
  amber:      '#f59e0b',
  red:        '#ef4444',
  purple:     '#a855f7',
  trackBg:    '#334155',
  trackFill:  '#3b82f6',
}

// ── 슬라이더 설정 ────────────────────────────────────────────────
const SLIDERS = [
  {
    key:    'investable',
    label:  '초기 투자금',
    unit:   '만원',
    min:    0,
    max:    50000,
    step:   500,
    format: v => `${v.toLocaleString()}만원`,
    color:  C.blue,
  },
  {
    key:    'savings',
    label:  '월 적립금',
    unit:   '만원',
    min:    0,
    max:    500,
    step:   10,
    format: v => `${v.toLocaleString()}만원`,
    color:  C.purple,
  },
  {
    key:    'monthlyTarget',
    label:  '목표 월배당',
    unit:   '만원',
    min:    10,
    max:    500,
    step:   10,
    format: v => `${v.toLocaleString()}만원`,
    color:  C.green,
  },
  {
    key:    'fireAge',
    label:  '목표 FIRE 나이',
    unit:   '세',
    min:    30,
    max:    75,
    step:   1,
    format: v => `${v}세`,
    color:  C.amber,
  },
]

// ── 커스텀 슬라이더 ──────────────────────────────────────────────
function Slider({ config, value, onChange }) {
  const pct = ((value - config.min) / (config.max - config.min)) * 100

  return (
    <div style={{ marginBottom: 22 }}>
      {/* 레이블 + 현재값 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        alignItems: 'baseline', marginBottom: 6,
      }}>
        <span style={{ fontSize: 12, color: C.muted }}>{config.label}</span>
        <span style={{ fontSize: 15, fontWeight: 700, color: config.color }}>
          {config.format(value)}
        </span>
      </div>

      {/* 슬라이더 트랙 */}
      <div style={{ position: 'relative', height: 6 }}>
        {/* 배경 트랙 */}
        <div style={{
          position: 'absolute', inset: 0,
          background: C.trackBg, borderRadius: 3,
        }} />
        {/* 채워진 트랙 */}
        <div style={{
          position: 'absolute', top: 0, left: 0, bottom: 0,
          width: `${pct}%`, background: config.color,
          borderRadius: 3, transition: 'width 0.1s',
        }} />
        {/* input[range] — 실제 인터랙션 */}
        <input
          type="range"
          min={config.min}
          max={config.max}
          step={config.step}
          value={value}
          onChange={e => onChange(Number(e.target.value))}
          style={{
            position: 'absolute', inset: 0, width: '100%', height: '100%',
            opacity: 0, cursor: 'pointer', margin: 0,
          }}
        />
        {/* 썸 표시 (비주얼) */}
        <div style={{
          position: 'absolute', top: '50%',
          left: `${pct}%`, transform: 'translate(-50%, -50%)',
          width: 14, height: 14, borderRadius: '50%',
          background: config.color,
          border: `2px solid ${C.cardBg}`,
          boxShadow: `0 0 0 2px ${config.color}40`,
          pointerEvents: 'none',
          transition: 'left 0.1s',
        }} />
      </div>

      {/* 범위 레이블 */}
      <div style={{
        display: 'flex', justifyContent: 'space-between',
        marginTop: 4, fontSize: 10, color: '#475569',
      }}>
        <span>{config.format(config.min)}</span>
        <span>{config.format(config.max)}</span>
      </div>
    </div>
  )
}

// ── 결과 헤드라인 카드 ────────────────────────────────────────────
function HeadlineCard({ rv, fireAge }) {
  if (!rv) return null
  const { current_fire_age, gap_years, already_achievable, target_monthly_만원 } = rv

  if (already_achievable) {
    return (
      <div style={{
        background: 'linear-gradient(135deg, #064e3b 0%, #065f46 100%)',
        border: `1px solid ${C.green}60`,
        borderRadius: 14, padding: '18px 20px', marginBottom: 16,
      }}>
        <div style={{ fontSize: 13, color: '#6ee7b7', marginBottom: 4 }}>
          🎉 목표 달성 가능
        </div>
        <div style={{ fontSize: 18, fontWeight: 700, color: C.text }}>
          {fireAge}세에 월 {target_monthly_만원}만원 배당 달성!
        </div>
        <div style={{ fontSize: 12, color: '#86efac', marginTop: 6 }}>
          현재 조건으로 {current_fire_age}세 FIRE 가능 —
          목표보다 {fireAge - current_fire_age >= 0
            ? `${fireAge - current_fire_age}년 일찍`
            : `${current_fire_age - fireAge}년 늦게`} 달성
        </div>
      </div>
    )
  }

  return (
    <div style={{
      background: '#1e293b',
      border: `1px solid #475569`,
      borderRadius: 14, padding: '18px 20px', marginBottom: 16,
    }}>
      <div style={{ fontSize: 12, color: C.muted, marginBottom: 8 }}>FIRE 달성 시뮬레이션</div>

      {/* 목표 vs 현재 예상 — 시각적 비교 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
        {/* 목표 */}
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 11, color: C.muted }}>목표</div>
          <div style={{ fontSize: 28, fontWeight: 800, color: C.green,
                        lineHeight: 1.1 }}>{fireAge}세</div>
        </div>

        {/* 화살표 + 갭 */}
        <div style={{ flex: 1, textAlign: 'center' }}>
          <div style={{ color: C.red, fontSize: 13, fontWeight: 600 }}>
            {gap_years > 0 ? `${gap_years}년 부족 →` : '→'}
          </div>
          <div style={{ height: 2, background: C.red, margin: '4px 0',
                        opacity: 0.4, borderRadius: 1 }} />
        </div>

        {/* 현재 예상 */}
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 11, color: C.muted }}>현재 예상</div>
          <div style={{ fontSize: 28, fontWeight: 800,
                        color: gap_years > 0 ? C.red : C.green,
                        lineHeight: 1.1 }}>
            {current_fire_age >= 99 ? '달성불가' : `${current_fire_age}세`}
          </div>
        </div>
      </div>

      {/* 보조 설명 */}
      <div style={{ fontSize: 12, color: C.muted }}>
        {current_fire_age >= 99
          ? `현재 조건으로는 ${target_monthly_만원}만원/월 달성이 어렵습니다`
          : `월 ${target_monthly_만원}만원 배당 기준 — ${gap_years}년 차이`}
      </div>
    </div>
  )
}

// ── 역산 경로 카드 ────────────────────────────────────────────────
function PathCard({ icon, title, value, sub, color, highlight }) {
  return (
    <div style={{
      background: highlight ? `${color}15` : C.cardBg,
      border: `1px solid ${highlight ? color + '60' : C.cardBorder}`,
      borderRadius: 12, padding: '14px 16px', flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>
        {icon} {title}
      </div>
      <div style={{ fontSize: 17, fontWeight: 700, color, marginBottom: 3 }}>
        {value}
      </div>
      <div style={{ fontSize: 11, color: C.muted }}>{sub}</div>
    </div>
  )
}

// ── 역산 결과 섹션 ────────────────────────────────────────────────
function ResultSection({ rv, sliders }) {
  if (!rv) return (
    <div style={{
      padding: '32px', textAlign: 'center', color: C.muted, fontSize: 12,
      background: C.cardBg, borderRadius: 14, border: `1px solid ${C.cardBorder}`,
    }}>
      슬라이더를 조정하면 역산 결과가 여기에 나타납니다
    </div>
  )

  const {
    already_achievable,
    savings_increase    = 0,
    required_monthly_savings = 0,
    capital_increase    = 0,
    required_initial_capital = 0,
    achievable_monthly  = 0,
  } = rv

  const fmt = v => v.toLocaleString(undefined, { maximumFractionDigits: 0 })

  return (
    <div>
      <HeadlineCard rv={rv} fireAge={sliders.fireAge} />

      {/* 역산 3경로 */}
      {!already_achievable && (
        <>
          <div style={{ fontSize: 12, color: C.muted, marginBottom: 10 }}>
            ── 목표 달성 방법 3가지
          </div>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <PathCard
              icon="💰"
              title="월 적립금 추가"
              value={savings_increase > 0
                ? `+${fmt(savings_increase)}만원/월`
                : '현재 조건 충분'}
              sub={savings_increase > 0
                ? `총 ${fmt(required_monthly_savings)}만원/월로 달성`
                : '추가 저축 불필요'}
              color={C.blue}
              highlight={savings_increase > 0 && savings_increase < 200}
            />
            <PathCard
              icon="🏦"
              title="초기자산 추가"
              value={capital_increase > 0
                ? `+${fmt(capital_increase)}만원`
                : '현재 조건 충분'}
              sub={capital_increase > 0
                ? `총 ${fmt(required_initial_capital)}만원으로 달성`
                : '추가 자본 불필요'}
              color={C.purple}
              highlight={false}
            />
            <PathCard
              icon="📊"
              title="현재 조건 최대 달성"
              value={`${fmt(achievable_monthly)}만원/월`}
              sub="지금 조건으로 도달 가능한 최대"
              color={C.green}
              highlight={achievable_monthly >= rv.target_monthly_만원}
            />
          </div>
        </>
      )}

      {/* 이미 달성 가능한 경우에도 achievable 표시 */}
      {already_achievable && (
        <PathCard
          icon="📊"
          title="현재 조건 최대 달성 가능"
          value={`${fmt(achievable_monthly)}만원/월`}
          sub="현재 포트폴리오 조건 기준"
          color={C.green}
          highlight
        />
      )}

      {/* 메시지 */}
      {rv.message && (
        <div style={{
          marginTop: 14, padding: '10px 14px',
          background: '#0f172a', borderRadius: 10,
          fontSize: 12, color: C.muted,
          border: `1px solid ${C.cardBorder}`,
          lineHeight: 1.7,
        }}>
          {rv.message}
        </div>
      )}
    </div>
  )
}

// ── 메인 컴포넌트 ────────────────────────────────────────────────
export default function InteractiveSimulator({ portfolio }) {
  // ── 초기값: portfolio.input에서 가져오되 없으면 기본값 ──
  const inp = portfolio?.input ?? {}
  const sum = portfolio?.summary ?? {}

  const [sliders, setSliders] = useState({
    investable:    inp.investable        ?? 5000,
    savings:       sum.monthly_savings   ?? inp.monthly_savings  ?? 100,
    monthlyTarget: inp.monthly_target    ?? 100,
    fireAge:       inp.target_fire_age   ?? 55,
  })

  const [result,  setResult]  = useState(portfolio?.reverse_fire ?? null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  const timerRef = useRef(null)

  // portfolio prop이 바뀌면 슬라이더 초기값 동기화
  useEffect(() => {
    const i = portfolio?.input ?? {}
    const s = portfolio?.summary ?? {}
    setSliders({
      investable:    i.investable          ?? 5000,
      savings:       s.monthly_savings     ?? i.monthly_savings  ?? 100,
      monthlyTarget: i.monthly_target      ?? 100,
      fireAge:       i.target_fire_age     ?? 55,
    })
    setResult(portfolio?.reverse_fire ?? null)
  }, [portfolio])
  const currentAge = inp.age ?? 40

  // avg_net_yield: 포트폴리오 계산값 우선, 없으면 5.0
  const avgYield = sum.avg_dividend_yield_net ?? 5.0

  // ── debounced API 호출 ──
  useEffect(() => {
    clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      setLoading(true)
      setError(null)

      api.post('/api/portfolio/fire-reverse', {
        current_investable:   sliders.investable,
        monthly_savings:      sliders.savings,
        current_age:          currentAge,
        target_fire_age:      sliders.fireAge,
        'target_monthly_만원': sliders.monthlyTarget,
        avg_net_yield:        avgYield,
        div_growth_rate:      5.0,
        cpi_rate:             2.5,
      })
        .then(res  => setResult(res.data))
        .catch(err => {
          console.error('InteractiveSimulator API error:', err)
          setError('역산 계산에 실패했습니다. 잠시 후 다시 시도해주세요.')
        })
        .finally(() => setLoading(false))
    }, 300)

    return () => clearTimeout(timerRef.current)
  }, [sliders.investable, sliders.savings, sliders.monthlyTarget, sliders.fireAge])

  // ── 슬라이더 변경 핸들러 ──
  const updateSlider = (key, value) =>
    setSliders(prev => ({ ...prev, [key]: value }))

  return (
    <div style={{ width: '100%', color: C.text }}>

      {/* ── 헤더 ── */}
      <div style={{ marginBottom: 20 }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>
          FIRE 역산 시뮬레이터
        </div>
        <div style={{ fontSize: 12, color: C.muted }}>
          슬라이더를 조정하면 목표 달성에 필요한 조건이 자동으로 계산됩니다
          {loading && (
            <span style={{ marginLeft: 10, color: C.amber }}>
              ⟳ 계산 중...
            </span>
          )}
        </div>
      </div>

      {/* ── 2컬럼 레이아웃 (슬라이더 | 결과) ── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(260px, 380px) 1fr',
        gap: 20,
        alignItems: 'start',
      }}>

        {/* ── 왼쪽: 슬라이더 패널 ── */}
        <div style={{
          background: C.cardBg, border: `1px solid ${C.cardBorder}`,
          borderRadius: 14, padding: '20px 22px',
          opacity: loading ? 0.8 : 1, transition: 'opacity 0.2s',
        }}>
          {/* 고정 표시: 현재 나이 */}
          <div style={{
            display: 'flex', justifyContent: 'space-between',
            marginBottom: 20, paddingBottom: 16,
            borderBottom: `1px solid ${C.cardBorder}`,
          }}>
            <span style={{ fontSize: 12, color: C.muted }}>현재 나이 (고정)</span>
            <span style={{ fontSize: 15, fontWeight: 700, color: C.text }}>
              {currentAge}세
            </span>
          </div>

          {/* 슬라이더 4개 */}
          {SLIDERS.map(cfg => (
            <Slider
              key={cfg.key}
              config={cfg}
              value={sliders[cfg.key]}
              onChange={v => updateSlider(cfg.key, v)}
            />
          ))}

          {/* 리셋 버튼 */}
          <button
            onClick={() => setSliders({
              investable:    inp.investable     ?? 5000,
              savings:       sum.monthly_savings ?? inp.monthly_savings ?? 100,
              monthlyTarget: inp.monthly_target  ?? 100,
              fireAge:       inp.target_fire_age ?? 55,
            })}
            style={{
              marginTop: 4, width: '100%', padding: '8px',
              background: 'transparent', border: `1px solid ${C.cardBorder}`,
              borderRadius: 8, color: C.muted, fontSize: 12, cursor: 'pointer',
            }}
          >
            ↺ 초기값으로 리셋
          </button>
        </div>

        {/* ── 오른쪽: 결과 패널 ── */}
        <div>
          {error ? (
            <div style={{
              padding: '16px', color: C.red, fontSize: 12,
              background: C.cardBg, borderRadius: 14,
              border: `1px solid ${C.cardBorder}`,
            }}>
              {error}
            </div>
          ) : (
            <ResultSection rv={result} sliders={sliders} />
          )}
        </div>

      </div>

      {/* ── 반응형: 작은 화면에서 1컬럼 ── */}
      <style>{`
        @media (max-width: 700px) {
          .fire-simulator-grid {
            grid-template-columns: 1fr !important;
          }
        }
        input[type=range]::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 0; height: 0;
        }
        input[type=range]::-moz-range-thumb {
          width: 0; height: 0; border: none;
        }
      `}</style>

    </div>
  )
}
