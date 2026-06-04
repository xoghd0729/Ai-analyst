import { useState, useMemo } from 'react'
import {
  PieChart, Pie, Cell, Tooltip as PieTooltip, ResponsiveContainer,
  LineChart, Line, Area, AreaChart, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, Legend, ComposedChart,
} from 'recharts'
import api from '../api/client'
import HealthRadarChart    from '../components/HealthRadarChart'
import DividendCalendarHeatmap from '../components/DividendCalendarHeatmap'
import MonteCarloChart     from '../components/MonteCarloChart'
import CashflowMilestone   from '../components/CashflowMilestone'
import YieldTrapWarning    from '../components/YieldTrapWarning'
import PortfolioMonitor    from '../components/PortfolioMonitor'
import BacktestChart       from '../components/BacktestChart'
import './Portfolio.css'

const RISK_OPTIONS = [
  { value: 'conservative', label: '안정형', desc: '우량 종목 위주, 배당 안정성 최우선' },
  { value: 'moderate',     label: '중립형', desc: '안정성과 수익률 균형' },
  { value: 'aggressive',   label: '공격형', desc: 'Total Return 극대화, 성장 ETF 포함' },
]

const ASSET_COLOR = {
  kr_stock:   '#4f8ef7',   // 파랑
  us_div_etf: '#34d399',   // 초록
  kr_etf:     '#6ee7b7',   // 연초록
  us_reit:    '#fbbf24',   // 노랑
  kr_reit:    '#f59e0b',   // 주황
  defensive:  '#94a3b8',   // 회색
}

const GRADE_COLOR = {
  '🟢 우량': '#34d399',
  '🟡 보통': '#fbbf24',
  '🔴 위험': '#f87171',
}

// ── 계좌별 실효 세율 계산 ─────────────────────────────────────
// ISA: 비과세 한도 내 0%, 초과분 9.9% 분리과세
// 일반 한국주식: 15.4% (소득세 14% + 지방소득세 1.4%)
// 미국 ETF/리츠 (해외): 미국 원천징수 15% → 국내 추가 없음
// 연금저축: 과세이연, 수령 시 3.3~5.5% → 여기선 4% 근사
function calcAfterTaxYield(recommendations, annualYieldPct) {
  if (!recommendations?.length) return annualYieldPct * 0.846  // 기본 15.4% 제외

  let weightedTaxRate = 0
  let totalWeight = 0

  recommendations.forEach(r => {
    const w   = r.weight_pct / 100
    const acc = r.account || '일반'
    let taxRate = 0.154  // 기본: 한국 일반계좌

    if (acc.includes('ISA')) {
      taxRate = 0.055   // ISA: 9.9% 분리과세 (일반형) → 비과세 한도 후 약 5.5%p 절세
    } else if (acc.includes('연금')) {
      taxRate = 0.04    // 연금저축: 수령 시 3.3~5.5% → 4% 근사
    } else if (r.asset_class === 'us_div_etf' || r.asset_class === 'us_reit') {
      taxRate = 0.15    // 미국 원천징수 15%
    } else if (r.asset_class === 'kr_etf') {
      taxRate = 0.154   // 국내 ETF 분배금 15.4%
    }

    weightedTaxRate += w * taxRate
    totalWeight += w
  })

  const avgTax = totalWeight > 0 ? weightedTaxRate / totalWeight : 0.154
  return annualYieldPct * (1 - avgTax)
}

// ── 월별 배당 캘린더 계산 (메타데이터 기반) ─────────────────────
// 각 추천 종목에 pay_months 필드가 백엔드에서 직접 옴.
// rule-based fallback은 메타데이터 없을 때만 사용.
function calcMonthlyCashflow(recommendations) {
  const monthly = Array(12).fill(0)

  recommendations.forEach(r => {
    const annual = r.est_annual_div_만원 || 0
    // 백엔드 메타데이터 우선, 없으면 자산군 기반 fallback
    let months = r.pay_months
    if (!months || !months.length) {
      if (r.asset_class === 'kr_stock') months = [4]
      else if (r.asset_class === 'kr_reit') months = [3, 6, 9, 12]
      else if (['JEPI','JEPQ','O','TLT','BND'].includes(r.ticker)) {
        months = [1,2,3,4,5,6,7,8,9,10,11,12]
      } else {
        months = [3, 6, 9, 12]
      }
    }
    const perPayment = annual / months.length
    months.forEach(m => { monthly[m - 1] += perPayment })
  })

  return monthly.map((v, i) => ({
    month: i + 1,
    label: `${i + 1}월`,
    amount: Math.round(v * 10) / 10,
  }))
}

// ── 복리 성장 시뮬레이션 (세후) ──────────────────────────────
function calcCompoundGrowth(monthlyInvest, reserve, annualYieldPct, currentAge, monthlyTarget, afterTaxYield) {
  // 세전 yield로 포트폴리오 성장, 세후 yield로 실수령 배당 계산
  const growthYield  = annualYieldPct / 100 / 12        // 성장률 (복리 기준)
  const incomeYield  = (afterTaxYield ?? annualYieldPct * 0.846) / 100 / 12  // 세후 실수령
  let portfolio = reserve * 10000   // 만원 → 원
  const monthlyInvestWon = monthlyInvest * 10000
  const data = []
  let achieveAge = null

  for (let month = 0; month <= (75 - currentAge) * 12; month++) {
    portfolio = portfolio * (1 + growthYield) + monthlyInvestWon
    const monthlyDivAfterTax = portfolio * incomeYield   // 세후 월 배당
    const age = currentAge + month / 12

    if (month % 12 === 0) {
      data.push({
        age:           Math.round(age),
        portfolio:     Math.round(portfolio / 10000),
        monthlyDiv:    Math.round(monthlyDivAfterTax / 10000 * 100) / 100,
        monthlyDivPre: Math.round(portfolio * growthYield / 10000 * 100) / 100,
        invested:      Math.round((reserve * 10000 + monthlyInvestWon * month) / 10000),
      })
    }
    if (!achieveAge && monthlyDivAfterTax >= monthlyTarget * 10000) {
      achieveAge = age
    }
  }
  return { data, achieveAge }
}

// ── Monte Carlo 목표 달성 확률 시뮬레이션 ────────────────────
// 핵심 아이디어:
//   배당수익률은 고정값이 아니라 매년 ±변동이 있다.
//   1000번 시뮬레이션해서 "언제 목표 달성하는지"의 분포를 구한다.
//   결과: 달성 확률, 비관/중간/낙관 시나리오 연도
function runMonteCarlo(monthlyInvest, reserve, avgYield, afterTaxYield, currentAge, monthlyTarget, recs, N = 1000) {
  // ── 포트폴리오 가중 변동성 계산 (메타데이터 기반) ───────────
  // 각 자산의 실제 연간 변동성을 가중평균해서 포트폴리오 변동성 추정.
  // 상관관계는 단순화(완전 독립 가정)하여 분산 효과를 일부 반영.
  let weightedVar = 0
  let totalW = 0
  ;(recs || []).forEach(r => {
    const w   = (r.weight_pct || 0) / 100
    // 메타데이터에 volatility가 있으면 사용, 없으면 자산군 기본값
    const vol = (r.volatility_annual || (
      r.asset_class === 'kr_stock' ? 28.0 :
      r.asset_class === 'defensive' ? 7.0 : 15.0
    )) / 100  // 퍼센트 → 소수
    weightedVar += w * w * vol * vol  // 분산 (독립 가정)
    totalW += w
  })
  // 포트폴리오 변동성 (월 기준으로 환산)
  const portVolAnnual = Math.sqrt(weightedVar) * (totalW > 0 ? 1 / totalW : 1)
  const yieldStd = portVolAnnual * 0.4  // 배당 수익률 변동 ≈ 주가 변동의 40%

  const maxMonths = (80 - currentAge) * 12
  const targetWon = monthlyTarget * 10000
  const achieveAges = []

  // 정규분포 랜덤 (Box-Muller 변환)
  function randn() {
    const u1 = Math.random(), u2 = Math.random()
    return Math.sqrt(-2 * Math.log(u1 + 1e-10)) * Math.cos(2 * Math.PI * u2)
  }

  for (let sim = 0; sim < N; sim++) {
    let portfolio = reserve * 10000
    const monthlyInvestWon = monthlyInvest * 10000
    let achieved = null

    // 연간 수익률 충격: 해마다 독립적으로 변동
    for (let month = 0; month < maxMonths; month++) {
      if (month % 12 === 0) {
        // 매년 새로운 yield 샘플링
        var yearlyShock = randn() * yieldStd  // 연율 충격
      }
      const monthlyGrowth = (avgYield / 100 / 12) * (1 + yearlyShock * 12)  // 근사 월환산
      const monthlyIncome = (afterTaxYield / 100 / 12) * (1 + yearlyShock * 12)

      portfolio = portfolio * (1 + Math.max(monthlyGrowth, -0.05)) + monthlyInvestWon
      const monthlyDiv = portfolio * Math.max(monthlyIncome, 0)

      if (achieved === null && monthlyDiv >= targetWon) {
        achieved = currentAge + month / 12
      }
    }
    achieveAges.push(achieved)  // null이면 기간 내 미달성
  }

  const achieved = achieveAges.filter(a => a !== null).sort((a, b) => a - b)
  const totalAchieved = achieved.length
  const achieveProb = Math.round(totalAchieved / N * 100)

  // 분위수
  const p10Age = totalAchieved > 0 ? achieved[Math.floor(totalAchieved * 0.1)] : null
  const p50Age = totalAchieved > 0 ? achieved[Math.floor(totalAchieved * 0.5)] : null
  const p90Age = totalAchieved > 0 ? achieved[Math.floor(totalAchieved * 0.9)] : null

  // 팬 차트용 데이터: 나이별 P10/P50/P90 월배당
  // 세 시나리오의 복리 곡선 계산
  function simScenario(shockPct) {
    let pf = reserve * 10000
    const out = []
    for (let month = 0; month <= (75 - currentAge) * 12; month++) {
      const mg = (avgYield / 100 / 12) * (1 + shockPct)
      const ig = (afterTaxYield / 100 / 12) * (1 + shockPct)
      pf = pf * (1 + mg) + monthlyInvest * 10000
      if (month % 12 === 0) {
        out.push({
          age: Math.round(currentAge + month / 12),
          div: Math.round(pf * Math.max(ig, 0) / 10000 * 10) / 10,
        })
      }
    }
    return out
  }

  const pessimistic  = simScenario(-yieldStd * 1.5)   // 비관
  const base         = simScenario(0)                   // 기본
  const optimistic   = simScenario(+yieldStd * 1.5)    // 낙관

  // 팬 차트: 나이 기준으로 합치기
  const fanData = base.map((b, i) => ({
    age:       b.age,
    base:      b.div,
    low:       pessimistic[i]?.div ?? 0,
    high:      optimistic[i]?.div ?? 0,
    target:    monthlyTarget,
  }))

  return { achieveProb, p10Age, p50Age, p90Age, fanData, yieldStd }
}


// ── 포트폴리오 AI 설명 생성 (template 기반) ──────────────────
// LLM 없이 포트폴리오 구성을 분석해서 자연어 설명을 만든다.
// 핵심: 수치를 사람 말로 바꾸는 것.
function generatePortfolioInsight(recs, form, achieveProb, p50Age, risks) {
  if (!recs?.length) return null

  const riskLabel = { conservative: '안정형', moderate: '중립형', aggressive: '공격형' }[form.risk_tolerance] || '중립형'
  const age = Number(form.age)

  // 자산군별 비중 계산
  const weights = {}
  recs.forEach(r => {
    const cls = r.asset_class
    weights[cls] = (weights[cls] || 0) + (r.weight_pct || 0)
  })

  const krPct    = Math.round(weights.kr_stock || 0)
  const usPct    = Math.round((weights.us_div_etf || 0) + (weights.kr_etf || 0))
  const reitPct  = Math.round((weights.us_reit || 0) + (weights.kr_reit || 0))
  const defPct   = Math.round(weights.defensive || 0)

  // 월배당 ETF 비중
  const monthlyEtfTickers = ['JEPI', 'JEPQ', 'O', 'TLT', 'BND']
  const monthlyPct = recs
    .filter(r => monthlyEtfTickers.includes(r.ticker))
    .reduce((s, r) => s + (r.weight_pct || 0), 0)

  // 리스크 경보 있는지
  const hasRisk = risks?.length > 0
  const riskNames = risks?.map(r => r.name).join(', ') || ''

  // 섹터 집중도
  const sectorCounts = {}
  recs.forEach(r => {
    const s = r.asset_class
    sectorCounts[s] = (sectorCounts[s] || 0) + 1
  })

  // AI 설명 조각 생성
  const lines = []

  // ① 전략 요약
  lines.push(
    `${age}세 ${riskLabel} 투자자 기준으로 ` +
    `한국 배당주 ${krPct}% · 미국 ETF/리츠 ${usPct + reitPct}% · 방어형 ${defPct}% 구성을 추천합니다.`
  )

  // ② 월배당 흐름 진단
  if (monthlyPct >= 20) {
    lines.push(`JEPI·O 등 월배당 자산이 ${Math.round(monthlyPct)}% 포함되어 매월 고른 현금흐름을 확보합니다.`)
  } else {
    lines.push(`현재 구성은 분기·연간 배당 중심입니다. 월배당 ETF(JEPI 등) 추가 시 현금흐름이 평탄해집니다.`)
  }

  // ③ 달성 확률
  if (achieveProb >= 75) {
    lines.push(`Monte Carlo 분석 결과 목표 달성 확률 ${achieveProb}% — 현재 전략이 충분히 견고합니다.`)
  } else if (achieveProb >= 50) {
    lines.push(`목표 달성 확률 ${achieveProb}%. 월 투자금을 10~20% 늘리거나 목표 시기를 3~5년 연장하면 확률이 크게 개선됩니다.`)
  } else {
    lines.push(`목표 달성 확률 ${achieveProb}%. 목표 월배당 금액 조정 또는 투자 기간 연장을 검토하세요.`)
  }

  // ④ 리스크 경보
  if (hasRisk) {
    lines.push(`⚠️ AI 리스크 감지: ${riskNames}에서 배당 약화 신호가 포착됐습니다. 대체 종목으로의 점진적 비중 이동을 권장합니다.`)
  }

  // ⑤ 섹터 집중 경고
  if (krPct > 50) {
    lines.push(`한국 배당주 비중(${krPct}%)이 높아 국내 금리·정책 변수에 노출됩니다. 미국 ETF 비중을 높여 분산을 강화하세요.`)
  }

  return lines
}


// ── 섹션 네비게이션 정의 (sticky sidebar) ────────────────────
// 각 섹션의 id 와 라벨. id는 결과 화면의 <div id="..."> 에 매핑.
const RESULT_SECTIONS = [
  { id: 'sec-hero',       icon: '🎯', label: '목표 달성률' },
  { id: 'sec-recs',       icon: '📋', label: '추천 종목' },
  { id: 'sec-axis',       icon: '📐', label: '4축 배분' },
  { id: 'sec-growth',     icon: '📈', label: '복리 성장' },
  { id: 'sec-cashflow',   icon: '💰', label: '월별 현금흐름' },
  { id: 'sec-backtest',   icon: '📊', label: '21년 백테스팅' },
  { id: 'sec-montecarlo', icon: '🎲', label: 'Monte Carlo' },
  { id: 'sec-survival',   icon: '🛡️', label: '소득 지속성' },
  { id: 'sec-health',     icon: '❤️', label: '건강 진단' },
  { id: 'sec-monitor',    icon: '📍', label: '관리 대시보드' },
]


// ── 데모 페르소나 3종 (캡스톤 발표용) ─────────────────────────
// 각 페르소나 = "안전한 배당 + 주가 유지 + 복리" 철학의 3가지 인생 단계
const PERSONAS = [
  {
    key:   'yunji',
    icon:  '👩‍💼',
    title: '28세 윤지',
    label: '적립형 신입사원',
    desc:  '월 100만원 적립 · 50세 FIRE 목표',
    form:  {
      age: 28, monthly_invest: 100, reserve: 1000,
      monthly_target: 200, risk_tolerance: 'moderate',
    },
  },
  {
    key:   'minho',
    icon:  '👨‍👩‍👧',
    title: '42세 민호',
    label: '균형형 가장',
    desc:  '자산 1.5억 · 자녀 + 본인 노후',
    form:  {
      age: 42, monthly_invest: 100, reserve: 15000,
      monthly_target: 250, risk_tolerance: 'conservative',
    },
  },
  {
    key:   'youngja',
    icon:  '👵',
    title: '55세 영자',
    label: '인출형 은퇴 준비',
    desc:  '자산 5억 · 즉시 월 200만원 인출',
    form:  {
      age: 55, monthly_invest: 0, reserve: 50000,
      monthly_target: 200, risk_tolerance: 'conservative',
    },
  },
]

export default function Portfolio() {
  const [form, setForm] = useState({
    age:            25,
    monthly_invest: 30,
    reserve:        0,
    monthly_target: 50,
    risk_tolerance: 'moderate',
  })
  const [result,    setResult]    = useState(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState(null)
  const [activePersona, setActivePersona] = useState(null)

  const handleChange = (key, val) => {
    setForm(f => ({ ...f, [key]: val }))
    setActivePersona(null)  // 수동 변경 시 페르소나 표시 해제
  }

  // 단일 진실의 원천: form override를 받을 수 있게
  const runRecommend = async (overrideForm) => {
    const f = overrideForm || form
    setLoading(true); setError(null)
    try {
      const investable = Number(f.monthly_invest) * 12 + Number(f.reserve)
      const res = await api.post('/api/portfolio/recommend', {
        age:               Number(f.age),
        annual_income:     Number(f.monthly_invest) * 12,
        monthly_target:    Number(f.monthly_target),
        investable_amount: investable,
        risk_tolerance:    f.risk_tolerance,
      })
      setResult({
        ...res.data,
        monthly_invest: Number(f.monthly_invest),
        reserve:        Number(f.reserve),
        age:            Number(f.age),
        monthly_target: Number(f.monthly_target),
      })
    } catch {
      setError('서버 연결 실패. FastAPI 서버를 확인하세요.')
    } finally {
      setLoading(false)
    }
  }

  // 폼 제출 (수동)
  const handleSubmit = () => runRecommend()

  // 페르소나 자동 입력 + 즉시 추천 실행
  const handlePersonaClick = (persona) => {
    setForm(persona.form)
    setActivePersona(persona.key)
    runRecommend(persona.form)
  }

  // ── 세후 수익률 + 복리 시뮬레이션 + Monte Carlo + AI 설명 ───
  const { compoundData, achieveAge, afterTaxYield, cashflowData,
          mc, portfolioInsight } = useMemo(() => {
    if (!result) return {
      compoundData: [], achieveAge: null, afterTaxYield: 0,
      cashflowData: [], mc: null, portfolioInsight: null,
    }

    const avgYield = result.summary.avg_dividend_yield || 3.5
    const recs     = result.recommendations || []
    const atYield  = calcAfterTaxYield(recs, avgYield)
    const cashflow = calcMonthlyCashflow(recs)

    const { data, achieveAge } = calcCompoundGrowth(
      result.monthly_invest, result.reserve,
      avgYield, result.age, result.monthly_target, atYield,
    )

    // Monte Carlo: 1000회 시뮬레이션
    const mc = runMonteCarlo(
      result.monthly_invest, result.reserve,
      avgYield, atYield, result.age, result.monthly_target, recs, 1000,
    )

    // AI 포트폴리오 설명
    const insight = generatePortfolioInsight(
      recs, result, mc.achieveProb, mc.p50Age, result.risk_alerts,
    )

    return {
      compoundData: data, achieveAge, afterTaxYield: atYield,
      cashflowData: cashflow, mc, portfolioInsight: insight,
    }
  }, [result])

  // 도넛 데이터 (자산군별 색상)
  const donutData = result?.recommendations?.map(r => ({
    name:   r.name,
    value:  r.weight_pct,
    color:  ASSET_COLOR[r.asset_class] || '#4f8ef7',
    label:  r.asset_class_label,
    yield:  r.dividend_yield,
    tr:     r.total_return_pct,
  })) || []

  const s              = result?.summary || {}
  const avgYield       = s.avg_dividend_yield || 0
  const avgTotalReturn = s.avg_total_return_pct || 0
  const vsBank         = s.vs_bank_rate_pct || 0
  const bankRate       = s.bank_rate_pct || 3.5

  const yearsToGoal = achieveAge ? achieveAge - (result?.age || 25) : null
  const yearsInt    = yearsToGoal ? Math.floor(yearsToGoal) : null
  const monthsRem   = yearsToGoal ? Math.round((yearsToGoal - yearsInt) * 12) : null

  return (
    <div className="portfolio-page">
      <div className="page-header">
        <div className="page-title">
          AI Cashflow OS
          <span style={{
            marginLeft: 12, fontSize: 13, fontWeight: 500, color: 'var(--text-sub)',
            verticalAlign: 'middle',
          }}>
            — 미래 월급형 현금흐름을 설계·분석·방어·관리하는 시스템
          </span>
        </div>
        <div className="page-sub">
          배당수익률만이 아닌 <strong>Total Return (배당 + 자본차익)</strong>으로 은행 금리를 초과하는 현금흐름을 설계합니다
        </div>
      </div>

      <div className="portfolio-layout">
        {/* ── 입력 폼 ── */}
        <div className="card form-card">
          <h3 className="card-title">내 정보 입력</h3>

          {/* ── 데모 페르소나 빠른 선택 (캡스톤 발표용) ── */}
          <div style={{
            display: 'flex', flexDirection: 'column', gap: 6,
            padding: '12px 14px', marginBottom: 4,
            background: 'rgba(79,142,247,.06)',
            border: '1px dashed rgba(79,142,247,.35)',
            borderRadius: 10,
          }}>
            <div style={{
              fontSize: 11, fontWeight: 600, color: 'var(--text-sub)',
              letterSpacing: 0.5, textTransform: 'uppercase',
            }}>
              ⚡ 빠른 데모 — 페르소나 선택
            </div>
            <div style={{
              display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6,
            }}>
              {PERSONAS.map(p => {
                const active = activePersona === p.key
                return (
                  <button
                    key={p.key}
                    type="button"
                    onClick={() => handlePersonaClick(p)}
                    disabled={loading}
                    title={`${p.title} — ${p.label}\n${p.desc}`}
                    style={{
                      display: 'flex', flexDirection: 'column', alignItems: 'flex-start',
                      gap: 2, padding: '8px 10px',
                      background: active ? 'rgba(79,142,247,.15)' : 'var(--surface2)',
                      border: `1px solid ${active ? 'var(--blue)' : 'var(--border)'}`,
                      borderRadius: 8, cursor: loading ? 'wait' : 'pointer',
                      transition: 'all 0.15s', textAlign: 'left',
                      opacity: loading && !active ? 0.5 : 1,
                    }}
                    onMouseEnter={e => {
                      if (!loading && !active) e.currentTarget.style.borderColor = 'var(--blue)'
                    }}
                    onMouseLeave={e => {
                      if (!active) e.currentTarget.style.borderColor = 'var(--border)'
                    }}
                  >
                    <div style={{ fontSize: 16 }}>{p.icon}</div>
                    <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>
                      {p.title}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-sub)' }}>
                      {p.label}
                    </div>
                  </button>
                )
              })}
            </div>
            {activePersona && (
              <div style={{ fontSize: 11, color: 'var(--text-sub)', marginTop: 2 }}>
                ✓ 페르소나 자동 입력 완료. 아래에서 값을 직접 조정해도 됩니다.
              </div>
            )}
          </div>

          <div className="form-group">
            <label>나이</label>
            <div className="input-wrap">
              <input type="number" value={form.age}
                onChange={e => handleChange('age', e.target.value)} min={18} max={80} />
              <span className="input-unit">세</span>
            </div>
          </div>

          <div className="form-group">
            <label>월 투자 금액 <span className="label-sub">매달 적립</span></label>
            <div className="input-wrap">
              <input type="number" value={form.monthly_invest}
                onChange={e => handleChange('monthly_invest', e.target.value)} step={10} min={0} />
              <span className="input-unit">만원</span>
            </div>
          </div>

          <div className="form-group">
            <label>추가 여유자금 <span className="label-sub">없으면 0</span></label>
            <div className="input-wrap">
              <input type="number" value={form.reserve}
                onChange={e => handleChange('reserve', e.target.value)} step={100} min={0} />
              <span className="input-unit">만원</span>
            </div>
          </div>

          <div className="form-group">
            <label>목표 월 배당금</label>
            <div className="input-wrap">
              <input type="number" value={form.monthly_target}
                onChange={e => handleChange('monthly_target', e.target.value)} step={10} min={0} />
              <span className="input-unit">만원/월</span>
            </div>
          </div>

          <div className="form-group">
            <label>투자 성향</label>
            <div className="risk-options">
              {RISK_OPTIONS.map(opt => (
                <button key={opt.value}
                  className={`risk-btn ${form.risk_tolerance === opt.value ? 'active' : ''}`}
                  onClick={() => handleChange('risk_tolerance', opt.value)}>
                  <div className="risk-label">{opt.label}</div>
                  <div className="risk-desc">{opt.desc}</div>
                </button>
              ))}
            </div>
          </div>

          <button className="btn btn-primary submit-btn" onClick={handleSubmit} disabled={loading}>
            {loading ? '⏳ 분석 중...' : '🚀 포트폴리오 추천받기'}
          </button>
          {error && <div className="error-box" style={{ marginTop: 12 }}>{error}</div>}
        </div>

        {/* ── 섹션 네비게이션 — 결과 있을 때만 floating sidebar ── */}
        {result && (
          <nav
            aria-label="섹션 빠른 점프"
            style={{
              position: 'fixed', right: 16, top: '50%',
              transform: 'translateY(-50%)',
              display: 'flex', flexDirection: 'column', gap: 4,
              padding: '10px 8px',
              background: 'rgba(15, 23, 42, 0.92)',
              backdropFilter: 'blur(8px)',
              border: '1px solid #1e293b',
              borderRadius: 12,
              zIndex: 50,
              maxHeight: '80vh', overflowY: 'auto',
            }}
          >
            <div style={{
              fontSize: 9, color: '#64748b', fontWeight: 700,
              textTransform: 'uppercase', letterSpacing: 0.6,
              textAlign: 'center', marginBottom: 4,
            }}>
              빠른 이동
            </div>
            {RESULT_SECTIONS.map(s => (
              <a
                key={s.id}
                href={`#${s.id}`}
                onClick={(e) => {
                  e.preventDefault()
                  const el = document.getElementById(s.id)
                  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '6px 10px', borderRadius: 8,
                  fontSize: 11, color: '#cbd5e1',
                  textDecoration: 'none', cursor: 'pointer',
                  transition: 'background 0.15s',
                  whiteSpace: 'nowrap',
                }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(79,142,247,.15)'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                title={s.label}
              >
                <span style={{ fontSize: 14 }}>{s.icon}</span>
                <span>{s.label}</span>
              </a>
            ))}
          </nav>
        )}

        {/* ── 결과 ── */}
        {result ? (
          <div className="result-section">

            {/* HERO */}
            <div id="sec-hero" className="hero-card">
              <div className="hero-grid">

                {/* ① Monte Carlo 달성 확률 — 메인 지표 */}
                <div className="hero-item main">
                  <div className="hero-label">🎯 목표 달성 확률</div>
                  {mc ? (
                    <>
                      <div className="hero-value highlight">
                        <span className={`hv-num ${mc.achieveProb >= 70 ? 'green' : mc.achieveProb >= 50 ? 'yellow' : 'red'}`}>
                          {mc.achieveProb}
                        </span>
                        <span className="hv-unit">%</span>
                      </div>
                      <div className="hero-sub">
                        1,000회 시뮬레이션 기준
                        {mc.p50Age && ` · 중간값 ${Math.ceil(mc.p50Age)}세 달성`}
                      </div>
                      {/* 시나리오 범위 */}
                      <div className="scenario-row">
                        <span className="sc-item pessimistic">
                          비관 {mc.p10Age ? `${Math.ceil(mc.p10Age)}세` : '미달성'}
                        </span>
                        <span className="sc-sep">·</span>
                        <span className="sc-item base">
                          중간 {mc.p50Age ? `${Math.ceil(mc.p50Age)}세` : '미달성'}
                        </span>
                        <span className="sc-sep">·</span>
                        <span className="sc-item optimistic">
                          낙관 {mc.p90Age ? `${Math.ceil(mc.p90Age)}세` : '미달성'}
                        </span>
                      </div>
                    </>
                  ) : (
                    <div className="hero-value" style={{ fontSize: 16 }}>계산 중...</div>
                  )}
                </div>

                <div className="hero-item">
                  <div className="hero-label">📈 Total Return (연)</div>
                  <div className="hero-value">
                    <span className={`hv-num ${avgTotalReturn > 0 ? 'green' : ''}`}>{avgTotalReturn}</span>
                    <span className="hv-unit">%</span>
                  </div>
                  <div className="hero-sub">
                    배당 {avgYield}% + 자본차익 {(avgTotalReturn - avgYield).toFixed(1)}%
                  </div>
                </div>

                <div className="hero-item">
                  <div className="hero-label">🏦 은행 대비 초과수익</div>
                  <div className="hero-value">
                    <span className={`hv-num ${vsBank > 0 ? 'green' : 'red'}`}>
                      {vsBank > 0 ? '+' : ''}{vsBank}
                    </span>
                    <span className="hv-unit">%p</span>
                  </div>
                  <div className="hero-sub">예금 {bankRate}% 대비</div>
                </div>

              </div>
            </div>

            {/* AI 포트폴리오 설명 */}
            {portfolioInsight?.length > 0 && (
              <div className="card ai-insight-card">
                <h3 className="card-title">
                  🤖 AI 포트폴리오 진단
                  <span className="title-sub">구성·리스크·달성 가능성 종합 분석</span>
                </h3>
                <div className="insight-lines">
                  {portfolioInsight.map((line, i) => (
                    <div key={i} className={`insight-line ${line.startsWith('⚠️') ? 'warn' : ''}`}>
                      <span className="il-dot" />
                      {line}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* ── AI 리스크 경보 ── */}
            {result.risk_alerts?.length > 0 && (
              <div className="card risk-alert-card">
                <h3 className="card-title">
                  ⚠️ AI 배당 리스크 경보
                  <span className="title-sub">{result.risk_alerts.length}개 종목에서 신호 감지</span>
                </h3>
                <div className="risk-alert-list">
                  {result.risk_alerts.map((alert, i) => (
                    <div key={i} className={`risk-alert-item severity-${alert.severity}`}>
                      <div className="ra-header">
                        <span className="ra-icon">{alert.status === 'BROKEN' ? '🔴' : '🟡'}</span>
                        <span className="ra-name">{alert.name}</span>
                        <span className="ra-badge">{alert.status}</span>
                        <span className="ra-weight">포트폴리오 {alert.weight_pct}%</span>
                        <span className="ra-prob">
                          {alert.status === 'BROKEN'
                            ? `삭감확률 ${(alert.P_BROKEN * 100).toFixed(0)}%`
                            : `약화확률 ${(alert.P_WEAKENING * 100).toFixed(0)}%`}
                        </span>
                      </div>
                      <div className="ra-message">{alert.message}</div>
                      {alert.alternative && (
                        <div className="ra-alternative">
                          💡 대체 검토: <strong>{alert.alternative.name}</strong> — {alert.alternative.reason}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 4축 구성 요약 + 분산 근거 설명 */}
            {result.axis_summary?.length > 0 && (
              <div id="sec-axis" className="card" style={{ scrollMarginTop: 16 }}>
                <h3 className="card-title">📐 4축 자산 배분 요약</h3>

                {/* 분산 근거 한 줄 — "왜 종목당 비중이 작은지" 답 */}
                {(() => {
                  const recs = result.recommendations || []
                  const totalCount = recs.length
                  if (totalCount === 0) return null
                  const maxRec = recs.reduce(
                    (best, r) => (r.weight_pct > best.weight_pct ? r : best),
                    recs[0]
                  )
                  const avgWeight = totalCount > 0 ? (100 / totalCount).toFixed(1) : '0'
                  return (
                    <div style={{
                      marginBottom: 14, padding: '10px 14px',
                      background: 'rgba(79,142,247,.06)',
                      borderRadius: 8, border: '1px solid rgba(79,142,247,.2)',
                      fontSize: 12, color: '#94a3b8', lineHeight: 1.6,
                    }}>
                      <div style={{ color: '#cbd5e1', fontWeight: 600, marginBottom: 4 }}>
                        ⚖️ 분산 방식 — 자산군 비중 × 종목 점수 비례
                      </div>
                      총 <strong style={{ color: '#60a5fa' }}>{totalCount}개</strong> 종목,
                      평균 <strong style={{ color: '#60a5fa' }}>{avgWeight}%</strong> 비중.
                      최대 비중 <strong style={{ color: '#60a5fa' }}>
                      {maxRec.ticker} ({maxRec.weight_pct?.toFixed(1)}%)
                      </strong>.
                      <br/>
                      단일 종목 의존을 줄여 한 종목이 배당 삭감해도 전체 영향 최소화.
                    </div>
                  )
                })()}

                <div className="axis-summary-grid">
                  {result.axis_summary.map((ax, i) => (
                    <div key={i} className="axis-item"
                      style={{ borderLeft: `3px solid ${ASSET_COLOR[ax.asset_class] || '#4f8ef7'}` }}>
                      <div className="ax-label">{ax.label}</div>
                      <div className="ax-weight">{ax.weight_pct}%</div>
                      <div className="ax-yields">
                        배당 {ax.avg_div_yield}%
                        <span className="ax-tr"> / TR {ax.avg_total_return}%</span>
                      </div>
                      <div className="ax-count">{ax.count}개 자산</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 복리 성장 그래프 */}
            <div id="sec-growth" className="card" style={{ scrollMarginTop: 16 }}>
              <h3 className="card-title">
                📈 복리 성장 곡선
                <span className="title-sub">매달 {result.monthly_invest}만원 × 배당 재투자 · 세후 기준</span>
              </h3>
              {/* 세후 수익률 요약 배지 */}
              <div className="tax-summary-row">
                <div className="tax-badge">
                  <span className="tb-label">세전 배당수익률</span>
                  <span className="tb-value">{avgYield}%</span>
                </div>
                <span className="tax-arrow">→</span>
                <div className="tax-badge accent">
                  <span className="tb-label">세후 실효 수익률</span>
                  <span className="tb-value green">{afterTaxYield.toFixed(2)}%</span>
                </div>
                <div className="tax-badge info">
                  <span className="tb-label">절세 효과</span>
                  <span className="tb-value">{(avgYield - afterTaxYield).toFixed(2)}%p 절감</span>
                </div>
              </div>
              {/* 팬 차트: 비관/기본/낙관 시나리오 */}
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart data={mc?.fanData || []} margin={{ top: 10, right: 20, left: 10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="age" tick={{ fontSize: 12, fill: 'var(--text-sub)' }}
                    tickFormatter={v => `${v}세`} />
                  <YAxis tick={{ fontSize: 11, fill: 'var(--text-sub)' }}
                    tickFormatter={v => `${v}만`} width={55} />
                  <Tooltip
                    contentStyle={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 8 }}
                    formatter={(val, name) => [`${val}만원/월`, name]}
                    labelFormatter={v => `${v}세`}
                  />
                  <Legend wrapperStyle={{ fontSize: 12, color: 'var(--text-sub)' }} />

                  {/* 신뢰구간 음영 */}
                  <Area type="monotone" dataKey="high" fill="rgba(52,211,153,0.12)"
                    stroke="none" name="낙관 시나리오" legendType="none" />
                  <Area type="monotone" dataKey="low" fill="var(--surface)"
                    stroke="none" name="비관 시나리오" legendType="none" />

                  {/* 목표선 */}
                  <ReferenceLine y={result.monthly_target} stroke="#fbbf24" strokeDasharray="4 4"
                    label={{ value: `목표 ${result.monthly_target}만원`, fill: '#fbbf24', fontSize: 11, position: 'right' }} />

                  {/* 중간 달성 시점 */}
                  {mc?.p50Age && (
                    <ReferenceLine x={Math.ceil(mc.p50Age)} stroke="#34d399" strokeDasharray="4 4"
                      label={{ value: `🎯 ${Math.ceil(mc.p50Age)}세`, fill: '#34d399', fontSize: 11, position: 'top' }} />
                  )}

                  <Line type="monotone" dataKey="high" stroke="rgba(52,211,153,0.4)"
                    strokeWidth={1} dot={false} name="낙관" />
                  <Line type="monotone" dataKey="base" stroke="#34d399"
                    strokeWidth={2.5} dot={false} name="기본(세후)" />
                  <Line type="monotone" dataKey="low" stroke="rgba(148,163,184,0.6)"
                    strokeWidth={1} dot={false} name="비관" />
                </ComposedChart>
              </ResponsiveContainer>
              <div className="chart-note">
                💡 1,000회 Monte Carlo 시뮬레이션 | 음영 = 수익률 변동 구간 | 기본선 = 세후 수익률 기준
              </div>
            </div>

            {/* 월배당 현금흐름 캘린더 */}
            <div className="card">
              <h3 className="card-title">
                📅 월배당 현금흐름 캘린더
                <span className="title-sub">현재 포트폴리오 기준 월별 예상 배당 수령</span>
              </h3>
              <div className="cashflow-grid">
                {cashflowData.map(({ month, label, amount }) => (
                  <div key={month} className={`cf-month ${amount > 0 ? 'has-div' : 'no-div'}`}>
                    <div className="cf-label">{label}</div>
                    <div className="cf-bar-wrap">
                      <div className="cf-bar"
                        style={{
                          height: `${Math.min(amount / (Math.max(...cashflowData.map(d=>d.amount)) || 1) * 80, 80)}px`,
                          background: amount > 0 ? 'var(--green, #34d399)' : 'var(--border)',
                          opacity: amount > 0 ? 1 : 0.3,
                        }}
                      />
                    </div>
                    <div className={`cf-amount ${amount > 0 ? 'green' : 'muted'}`}>
                      {amount > 0 ? `${amount}만` : '—'}
                    </div>
                  </div>
                ))}
              </div>
              <div className="chart-note">
                💡 JEPI·O 등 월배당 ETF 편입 시 매월 고른 현금흐름 확보 가능 | 한국 배당주는 주로 4월 집중
              </div>
            </div>

            {/* 도넛 + 종목 근거 */}
            <div className="card">
              <h3 className="card-title">🧩 AI 포트폴리오 구성
                <span className="title-sub">4축 가중 배분</span>
              </h3>
              <div className="donut-layout">
                <div className="donut-wrap">
                  <ResponsiveContainer width={240} height={240}>
                    <PieChart>
                      <Pie data={donutData} cx="50%" cy="50%"
                        innerRadius={70} outerRadius={110}
                        dataKey="value" labelLine={false}>
                        {donutData.map((entry, i) => (
                          <Cell key={i} fill={entry.color} stroke="var(--surface)" strokeWidth={2} />
                        ))}
                      </Pie>
                      <PieTooltip
                        formatter={(v, n, p) => [
                          `${v}% | TR ${p.payload.tr}%`,
                          p.payload.name
                        ]}
                        contentStyle={{ background: 'var(--surface2)', border: '1px solid var(--border)', borderRadius: 8 }} />
                    </PieChart>
                  </ResponsiveContainer>
                  <div className="donut-center-text">
                    <div className="dct-value">{avgTotalReturn}%</div>
                    <div className="dct-label">Total Return</div>
                  </div>
                </div>

                {/* 종목별 근거 */}
                <div className="stock-reasons">
                  {result.recommendations.slice(0, 6).map((r, i) => (
                    <div key={i} className="reason-card">
                      <div className="rc-header">
                        <span className="rc-dot" style={{ background: ASSET_COLOR[r.asset_class] || '#4f8ef7' }} />
                        <span className="rc-name">{r.name}</span>
                        <span className="rc-weight">{r.weight_pct}%</span>
                      </div>
                      <div className="rc-badge-row">
                        <span className="rc-asset-badge">{r.asset_class_label}</span>
                        <span className="rc-account-badge"
                          style={{ background: r.account.includes('ISA') ? 'rgba(52,211,153,.15)' : 'rgba(79,142,247,.1)',
                                   color: r.account.includes('ISA') ? 'var(--green)' : 'var(--blue)' }}>
                          {r.account}
                        </span>
                      </div>
                      <div className="rc-tr">
                        배당 {r.dividend_yield ? Number(r.dividend_yield).toFixed(1) : '-'}%
                        {r.capital_gain_rate > 0 && ` + 주가성장 ${r.capital_gain_rate}% = TR ${r.total_return_pct}%`}
                      </div>
                      <div className="rc-reason">{r.description}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* 추천 종목 테이블 */}
            <div id="sec-recs" className="card" style={{ scrollMarginTop: 16 }}>
              <h3 className="card-title">📋 종목별 적립 배분</h3>
              <YieldTrapWarning yieldTraps={result.yield_traps || []} />
              <table className="rec-table">
                <thead>
                  <tr>
                    <th>종목명 / 자산군</th>
                    <th>계좌</th>
                    <th>배당수익률</th>
                    <th>Total Return</th>
                    <th>AI 리스크</th>
                    <th>비중</th>
                    <th>월 배당(예상)</th>
                  </tr>
                </thead>
                <tbody>
                  {result.recommendations.map((r, i) => (
                    <tr key={i} className={r.ml_status === 'BROKEN' ? 'row-broken' : r.ml_status === 'WEAKENING' ? 'row-weakening' : ''}>
                      <td>
                        <div className="rec-name">{r.name}</div>
                        <div className="rec-asset-label" style={{ color: ASSET_COLOR[r.asset_class] }}>
                          {r.asset_class_label}
                        </div>
                      </td>
                      <td>
                        <span className={`badge ${r.account.includes('ISA') ? 'badge-green' : 'badge-blue'}`}>
                          {r.account}
                        </span>
                      </td>
                      <td className="num">{r.dividend_yield ? `${Number(r.dividend_yield).toFixed(1)}%` : '-'}</td>
                      <td className="num green">
                        {r.total_return_pct > 0 ? `${r.total_return_pct}%` : '-'}
                      </td>
                      <td className="num">
                        {r.ml_status ? (
                          <span className={`ml-badge ml-${r.ml_status?.toLowerCase()}`}>
                            {r.ml_icon} {r.ml_status}
                          </span>
                        ) : <span className="ml-badge ml-intact">⚪ N/A</span>}
                      </td>
                      <td className="num">{r.weight_pct}%</td>
                      <td className="num green">{r.est_monthly_div_만원}만원</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="chart-note" style={{ textAlign: 'left', marginTop: 8 }}>
                💡 Total Return = 배당수익률 + 자본차익(주가성장) 근사값 | 은행 예금({bankRate}%) 초과 여부로 비교
              </div>
            </div>

            {/* ISA 절세 전략 */}
            <div className="card isa-card">
              <h3 className="card-title">💰 ISA 절세 전략</h3>
              <div className="isa-grid">
                <div className="isa-item">
                  <div className="isa-label">계좌 유형</div>
                  <div className="isa-value blue">{result.isa_strategy.isa_type}</div>
                </div>
                <div className="isa-item">
                  <div className="isa-label">연간 납입 권장</div>
                  <div className="isa-value">{result.isa_strategy.recommended_annual.toLocaleString()}만원</div>
                </div>
                <div className="isa-item">
                  <div className="isa-label">비과세 한도</div>
                  <div className="isa-value green">{result.isa_strategy.tax_free_limit}만원</div>
                </div>
                <div className="isa-item">
                  <div className="isa-label">세율 혜택</div>
                  <div className="isa-value">{result.isa_strategy.tax_rate}</div>
                </div>
              </div>
              <div className="isa-tip">💡 {result.isa_strategy.tip}</div>
              <div className="rebalancing-tip">🔄 {result.rebalancing_tip}</div>
            </div>

            {/* ══ 신규 분석 패널 ══════════════════════════════════════ */}

            {/* 현금흐름 마일스톤 — "내 인생이 어떻게 변하나" */}
            <div id="sec-cashflow" style={{ scrollMarginTop: 16 }}>
              <CashflowMilestone
                summary={result.summary}
                fire_plan={result.fire_plan}
              />
            </div>

            {/* Portfolio Health OS 레이더 차트 */}
            {result.portfolio_health && (
              <div id="sec-health" style={{ scrollMarginTop: 16 }}>
                <HealthRadarChart health={result.portfolio_health} />
              </div>
            )}

            {/* 배당 캘린더 히트맵 */}
            {result.dividend_calendar && (
              <DividendCalendarHeatmap calendar={result.dividend_calendar} />
            )}

            {/* Monte Carlo 밴드 차트 (백엔드 MC 결과 우선, 없으면 프론트 mc) */}
            {(result.monte_carlo?.p50_monthly || mc?.fanData) && (
              <div id="sec-montecarlo" style={{ scrollMarginTop: 16 }}>
                <MonteCarloChart
                  monteCarlo={result.monte_carlo || {
                    p10_monthly: mc.fanData?.map(d => d.p10) || [],
                    p50_monthly: mc.fanData?.map(d => d.p50) || [],
                    p90_monthly: mc.fanData?.map(d => d.p90) || [],
                    years: mc.fanData?.map((_, i) => i + 1) || [],
                    p50_final: mc.fanData?.[mc.fanData.length-1]?.p50 || 0,
                    p10_final: mc.fanData?.[mc.fanData.length-1]?.p10 || 0,
                    confidence_at_target: mc.achieveProb || 0,
                    expected_cut_events: 0,
                  }}
                  monthlyTarget={result.monthly_target}
                />
              </div>
            )}

            {/* 포트폴리오 생존확률 (ML + 상관충격 통합 헤드라인) */}
            {result.survival?.survival_probability != null && (() => {
              const s = result.survival
              const score = s.income_sustainability_score ?? s.survival_probability
              const color = score >= 75 ? '#34d399' : score >= 55 ? '#fbbf24' : '#f87171'
              const weightMap = Object.fromEntries(s.concentration_groups || [])
              const cmp = s.compare
              return (
                <div id="sec-survival" className="card" style={{ scrollMarginTop: 16 }}>
                  <h3 className="card-title">
                    🛡️ 소득 지속성 점수
                    <span className="title-sub">ML·Monte Carlo·집중도 통합 — "이 월배당이 20년 뒤에도 나오는가"</span>
                  </h3>
                  <div style={{ display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap', padding: '8px 4px' }}>
                    <div style={{ textAlign: 'center', minWidth: 140 }}>
                      <div style={{ fontSize: 52, fontWeight: 800, color, lineHeight: 1.1 }}>{score}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted, #94a3b8)', marginTop: 4 }}>소득 지속성 점수 / 100</div>
                    </div>
                    <div style={{ flex: 1, minWidth: 220, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                      <div><div style={{ fontSize: 11, color: 'var(--text-muted,#94a3b8)' }}>20년 지속 확률</div>
                        <div style={{ fontSize: 18, fontWeight: 700 }}>{s.survival_probability}%</div></div>
                      <div><div style={{ fontSize: 11, color: 'var(--text-muted,#94a3b8)' }}>만기 유지 확률</div>
                        <div style={{ fontSize: 18, fontWeight: 700 }}>{s.endpoint_probability}%</div></div>
                      <div><div style={{ fontSize: 11, color: 'var(--text-muted,#94a3b8)' }}>지속 기준선</div>
                        <div style={{ fontSize: 18, fontWeight: 700 }}>{s.threshold_monthly_만원}만원</div></div>
                      <div><div style={{ fontSize: 11, color: 'var(--text-muted,#94a3b8)' }}>비관 시 최악연도</div>
                        <div style={{ fontSize: 18, fontWeight: 700 }}>{s.p10_worst_real}만원</div></div>
                    </div>
                  </div>

                  {s.risk_contribution?.length > 0 && (
                    <div style={{ marginTop: 14 }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted,#94a3b8)', marginBottom: 6 }}>
                        위험 기여도 (비중이 아니라 실제 위험) — 비중과 다르면 숨은 집중
                      </div>
                      <div style={{ display: 'flex', height: 12, borderRadius: 6, overflow: 'hidden' }}>
                        {s.risk_contribution.map(([g, pct], i) => (
                          <div key={g} title={`${g} 위험 ${pct}%`} style={{
                            width: `${pct}%`,
                            background: ['#f87171','#fbbf24','#4f8ef7','#34d399','#a78bfa','#94a3b8'][i % 6],
                          }} />
                        ))}
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 6, fontSize: 11 }}>
                        {s.risk_contribution.slice(0, 5).map(([g, pct]) => (
                          <span key={g} style={{ color: 'var(--text-muted,#94a3b8)' }}>
                            {g}: 위험 <b style={{ color: '#e2e8f0' }}>{pct}%</b>
                            <span style={{ opacity: .5 }}> (비중 {weightMap[g] ?? 0}%)</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {cmp && cmp.delta_survival > 0 && (
                    <div style={{ marginTop: 14, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap',
                                  background: 'rgba(52,211,153,.08)', border: '1px solid rgba(52,211,153,.25)',
                                  borderRadius: 10, padding: '10px 14px' }}>
                      <div style={{ fontSize: 13 }}>
                        현재 생존 <b>{cmp.current.survival}%</b>
                        <span style={{ opacity: .6 }}> → </span>
                        분산보정 시 <b style={{ color: '#34d399' }}>{cmp.optimized.survival}%</b>
                      </div>
                      <div style={{ fontSize: 12, color: '#34d399', fontWeight: 700 }}>+{cmp.delta_survival}%p</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted,#94a3b8)' }}>{cmp.note}</div>
                    </div>
                  )}

                  <div className="chart-note" style={{ marginTop: 10 }}>💡 {s.summary}</div>
                </div>
              )
            })()}

            {/* 행동편향 진단 요약 */}
            {result.behavioral_finance?.bias_count > 0 && (
              <div style={{
                background: '#0f172a', borderRadius: 16, padding: '20px 24px',
                border: '1px solid #1e293b', marginTop: 0,
              }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginBottom: 12 }}>
                  행동편향 진단
                </div>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12,
                }}>
                  <div style={{ fontSize: 28 }}>
                    {result.behavioral_finance.investor_type?.split(' ')[0]}
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#e2e8f0' }}>
                      {result.behavioral_finance.investor_type}
                    </div>
                    <div style={{ fontSize: 12, color: '#64748b' }}>
                      {result.behavioral_finance.bias_count}가지 편향 탐지 ·{' '}
                      고위험 {result.behavioral_finance.high_severity}개
                    </div>
                  </div>
                </div>
                {result.behavioral_finance.biases?.slice(0, 3).map((b, i) => (
                  <div key={i} style={{
                    padding: '8px 12px', marginTop: 6,
                    background: '#111827', borderRadius: 8,
                    borderLeft: `3px solid ${b.severity === 'high' ? '#ef4444' : b.severity === 'medium' ? '#fbbf24' : '#64748b'}`,
                    fontSize: 12, color: '#94a3b8',
                  }}>
                    <span style={{ fontWeight: 600, color: '#e2e8f0' }}>{b.bias_name}</span>
                    {' — '}{b.message}
                  </div>
                ))}
              </div>
            )}

            {/* 스토리텔링 — 백엔드가 다양한 형태로 반환 (string / {narrative: {...}}) */}
            {(() => {
              const story = result.storytelling
              if (!story) return null

              // 가능한 형태:
              // 1. string                                  → 그대로 표시
              // 2. { narrative: "..." }                    → narrative 표시
              // 3. { narrative: { full_text: "..." } }     → full_text 표시
              // 4. { narrative: { headline, summary, ... } } → 섹션별 표시
              const extractText = (val) => {
                if (!val) return ''
                if (typeof val === 'string') return val
                if (typeof val === 'object') {
                  if (typeof val.full_text === 'string') return val.full_text
                  // 섹션 모음이면 합치기
                  const parts = ['headline', 'summary', 'strategy', 'future', 'risk', 'action']
                    .map(k => typeof val[k] === 'string' ? val[k] : '')
                    .filter(Boolean)
                  if (parts.length) return parts.join('\n\n')
                }
                return ''
              }

              const text = typeof story === 'string'
                ? story
                : extractText(story.narrative) || extractText(story)

              if (!text) return null

              return (
                <div style={{
                  background: '#0f172a', borderRadius: 16, padding: '20px 24px',
                  border: '1px solid #1e293b', marginTop: 0,
                }}>
                  <div style={{ fontSize: 15, fontWeight: 700, color: '#e2e8f0', marginBottom: 12 }}>
                    AI 분석 리포트
                  </div>
                  <div style={{
                    fontSize: 13, color: '#94a3b8', lineHeight: 1.8,
                    whiteSpace: 'pre-line',
                  }}>
                    {text}
                  </div>
                </div>
              )
            })()}

            {/* ── 21년 백테스팅 — "이 추천이 과거에도 통했는가?" ── */}
            <div id="sec-backtest" style={{ scrollMarginTop: 16 }}>
              <BacktestChart portfolio={result} startYear={2005} endYear={2024} />
            </div>

            <div id="sec-monitor" style={{ scrollMarginTop: 16 }}>
              <PortfolioMonitor
                calendar={result.dividend_calendar}
                rebalancingPlan={result.rebalancing_plan}
                recommendations={result.recommendations}
                projection={result.projection}
              />
            </div>

          </div>
        ) : (
          <div className="empty-result">
            <div className="er-icon">📊</div>
            <div className="er-title">정보를 입력하고 추천받기를 눌러보세요</div>
            <div className="er-desc">
              나이·월 투자금·목표 배당금을 입력하면<br/>
              AI가 4축 포트폴리오와 <strong>Total Return</strong> 기반 은행 금리 초과 달성 시점을 계산합니다
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
