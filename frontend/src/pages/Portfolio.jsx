import { useState, useMemo, useEffect } from 'react'
import * as auth from '../api/auth'
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
import BacktestChart         from '../components/BacktestChart'
import InteractiveSimulator    from '../components/InteractiveSimulator'
import EfficientFrontierChart  from '../components/EfficientFrontierChart'
import AdvisorPanel            from '../components/AdvisorPanel'
import CompareView             from '../components/CompareView'
import RationalePanel          from '../components/RationalePanel'
import ScoringRationale        from '../components/ScoringRationale'
import DataFreshnessPanel      from '../components/DataFreshnessPanel'
import StockRationaleCard      from '../components/StockRationaleCard'
import './Portfolio.css'

const RISK_OPTIONS = [
  {
    value: 'conservative', label: '안정형', desc: '우량 종목 위주, 배당 안정성 최우선',
    returnRange: '5~7%', mdd: '-15~-25%',
    composition: '채권형·리츠·배당성장 ETF 위주, 변동성 최소화',
    target: '은퇴자 및 보수적 투자자 (현금흐름 우선)',
  },
  {
    value: 'moderate', label: '중립형', desc: '안정성과 수익률 균형',
    returnRange: '7~10%', mdd: '-25~-35%',
    composition: '배당성장 ETF + 고배당주 혼합, 분기 배당 중심',
    target: '일반 직장인 (노후 준비 시작)',
  },
  {
    value: 'aggressive', label: '공격형', desc: 'Total Return 극대화, 성장 ETF 포함',
    returnRange: '10~14%', mdd: '-40~-60%',
    composition: '성장형 ETF + 배당성장주 + 고위험 리츠, 자본차익 추구',
    target: '장기 투자 가능 청년층 (20~30년 운용)',
  },
]

const ASSET_COLOR = {
  kr_stock:   '#2563eb',   // 파랑 (한국주식)
  us_stock:   '#7c3aed',   // 보라 (미국개별주)
  us_div_etf: '#059669',   // 초록 (미국배당ETF)
  kr_etf:     '#6ee7b7',   // 연초록 (국내ETF)
  us_reit:    '#d97706',   // 노랑 (미국리츠)
  kr_reit:    '#f59e0b',   // 주황 (한국리츠)
  defensive:  'var(--text-sub)',   // 회색 (방어형)
}

const GRADE_COLOR = {
  '🟢 우량': '#059669',
  '🟡 보통': '#d97706',
  '🔴 위험': '#dc2626',
}

// 인증 UI 스타일 헬퍼
const authBtn = (primary) => ({
  fontSize: 12, fontWeight: 600, padding: '5px 12px', borderRadius: 8, cursor: 'pointer',
  background: primary ? 'var(--blue)' : 'var(--surface2)',
  color: primary ? '#fff' : 'var(--text-sub)',
  border: `1px solid ${primary ? 'var(--blue)' : 'var(--border)'}`,
})
const modalInput = {
  width: '100%', marginTop: 8, padding: '9px 12px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--surface2)',
  color: 'var(--text)', fontSize: 14, boxSizing: 'border-box',
}

// 위험 기여 그룹별 한글 라벨 + "왜 위험한가" 설명
const GROUP_RISK_REASON = {
  reit:         { ko: '리츠',         why: '금리 민감도가 높아 비중 대비 위험이 큼' },
  kr_stock:     { ko: '국내 개별주',   why: '단일 시장·개별 종목이라 동시 충격에 취약' },
  kr_financial: { ko: '국내 금융주',   why: '위기 시 섹터 동시 배당컷 상관성이 높음' },
  kr_cyclical:  { ko: '국내 경기민감주', why: '경기 둔화 시 배당 변동성이 큼' },
  us_stock:     { ko: '미국 개별주',   why: '개별 기업 리스크에 직접 노출' },
  div_etf:      { ko: '배당 ETF',     why: '광범위 분산으로 위험 기여 낮음' },
  bond:         { ko: '방어형(채권)',  why: '배당컷 위험 최저' },
}

// 종목의 포트폴리오 내 '역할' — 왜 들어갔는가를 한 단어로
function holdingRole(r) {
  const y = r.dividend_yield || 0
  const cls = r.asset_class || ''
  if (cls === 'defensive') return { t: '방어·안정', c: '#2563eb' }
  if (cls.includes('reit')) return { t: '리츠 분산', c: '#7c3aed' }
  if (y >= 8)                return { t: '월배당 현금흐름', c: '#d97706' }
  if (r.etf_category === 'dividend_growth' || (r.consecutive_years || 0) >= 20)
                             return { t: '장기 배당성장', c: '#059669' }
  if (cls === 'us_stock')    return { t: '미국 배당주', c: '#059669' }
  if (cls === 'kr_stock')    return { t: '국내 배당', c: '#64748b' }
  return { t: '배당', c: '#64748b' }
}

// 종목별 "AI 선택 이유" — 기존 데이터로 2~3개 근거 합성 (왜 이 종목인가)
function selectionReasons(r) {
  const out = []
  const pbrk = (r.P_BROKEN ?? 0) * 100
  const pwkn = (r.P_WEAKENING ?? 0) * 100
  if (r.asset_class === 'kr_stock' && (r.P_BROKEN != null)) {
    out.push({ ok: pbrk + pwkn < 30, text: `배당컷 위험 ${Math.round(pbrk)}% (ML 검증)` })
  }
  if ((r.consecutive_years || 0) >= 10) out.push({ ok: true, text: `${r.consecutive_years}년 연속 증배` })
  if ((r.div_growth_rate_pct || 0) >= 5) out.push({ ok: true, text: `배당성장 ${Number(r.div_growth_rate_pct).toFixed(0)}%/년` })
  if (r.monthly_pay) out.push({ ok: true, text: '매월 배당 지급' })
  if (r.expense_ratio_pct != null && r.expense_ratio_pct > 0 && r.expense_ratio_pct <= 0.1)
    out.push({ ok: true, text: `저비용 보수 ${r.expense_ratio_pct}%` })
  if ((r.total_return_pct || 0) >= 8) out.push({ ok: true, text: `기대 총수익 ${r.total_return_pct}%` })
  if (out.length === 0 && (r.dividend_yield || 0) > 0)
    out.push({ ok: true, text: `배당수익률 ${Number(r.dividend_yield).toFixed(1)}%` })
  return out.slice(0, 3)
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
function calcCompoundGrowth(monthlyInvest, reserve, annualYieldPct, currentAge, monthlyTarget, afterTaxYield, investGrowthPct = 0) {
  // 세전 yield로 포트폴리오 성장, 세후 yield로 실수령 배당 계산
  const growthYield  = annualYieldPct / 100 / 12        // 성장률 (복리 기준)
  const incomeYield  = (afterTaxYield ?? annualYieldPct * 0.846) / 100 / 12  // 세후 실수령
  const gGrowth      = investGrowthPct / 100             // 적립금 연 증가율 (소득 상승)
  let portfolio = reserve * 10000   // 만원 → 원
  let monthlyInvestWon = monthlyInvest * 10000
  const data = []
  let achieveAge = null

  for (let month = 0; month <= (75 - currentAge) * 12; month++) {
    // 매년 적립금 증액 (소득 상승 반영) — 은퇴 나이(65) 이후엔 적립 중단
    if (month > 0 && month % 12 === 0 && currentAge + month / 12 <= 65) {
      monthlyInvestWon *= (1 + gGrowth)
    }
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
function runMonteCarlo(monthlyInvest, reserve, avgYield, afterTaxYield, currentAge, monthlyTarget, recs, N = 1000, investGrowthPct = 0) {
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

  const gGrowth = investGrowthPct / 100
  for (let sim = 0; sim < N; sim++) {
    let portfolio = reserve * 10000
    let monthlyInvestWon = monthlyInvest * 10000
    let achieved = null

    // 연간 수익률 충격: 해마다 독립적으로 변동
    for (let month = 0; month < maxMonths; month++) {
      if (month % 12 === 0) {
        // 매년 새로운 yield 샘플링
        var yearlyShock = randn() * yieldStd  // 연율 충격
        // 적립금 증액 (소득 상승, 65세까지)
        if (month > 0 && currentAge + month / 12 <= 65) monthlyInvestWon *= (1 + gGrowth)
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
  const achieveProb = Math.round(totalAchieved / N * 100)  // 적립 시뮬레이션 달성률 (월 적립 포함)

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

  const _risk = form.input?.risk_tolerance || form.risk_tolerance
  const riskLabel = { conservative: '안정형', moderate: '중립형', aggressive: '공격형' }[_risk] || '중립형'
  const age = Number(form.input?.age || form.age)

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
  { id: 'sec-hero',       icon: '🩺', label: '건강도 종합' },
  { id: 'sec-survival',   icon: '🛡️', label: '소득 지속성' },
  { id: 'sec-recs',       icon: '📋', label: '추천 종목' },
  { id: 'sec-shap',       icon: '🧠', label: '삭감 예측 근거(SHAP)' },
  { id: 'sec-axis',       icon: '📐', label: '4축 배분' },
  { id: 'sec-growth',     icon: '📈', label: '복리 성장' },
  { id: 'sec-cashflow',   icon: '💰', label: '월별 현금흐름' },
  { id: 'sec-montecarlo', icon: '🎲', label: 'Monte Carlo' },
  { id: 'sec-health',     icon: '❤️', label: '건강 진단' },
  { id: 'sec-monitor',    icon: '📍', label: '관리 대시보드' },
  { id: 'sec-advisor',    icon: '🤖', label: 'AI Advisor' },
  { id: 'sec-simulator',  icon: '🔢', label: 'FIRE 시뮬레이터' },
  { id: 'sec-frontier',   icon: '📐', label: 'MPT 효율적 프론티어' },
  { id: 'sec-compare',    icon: '⚖️', label: '포트폴리오 비교' },
  { id: 'sec-backtest',   icon: '📊', label: '검증 자료(백테스트)' },
]


// ── 발표 데모 고정 시나리오 (DEMO_RUNBOOK.md 기준값) ─────────────
// "25세가 50세에 월 200만원 배당을 받으려면?" 역산 스토리
const DEMO_PRESENTATION = {
  key:   'demo_presentation',
  icon:  '🎬',
  title: '발표 데모 시나리오',
  label: '25세 · 시드 5,000만 · 월 적립 100만',
  story: '"50세에 월 200만원 배당" 역산 시나리오',
  form: {
    age: 25, monthly_invest: 100, reserve: 5000,
    monthly_target: 100, risk_tolerance: 'moderate', invest_growth: 5,
  },
}

// ── 데모 페르소나 4종 (캡스톤 발표용 · 나이 단계별) ──────────────
// 같은 시스템이 인생 단계(25·35·45·60)에 따라 다른 배분·생존확률을 내는지 보여줌
const PERSONAS = [
  {
    key:   'age25',
    icon:  '🧑‍🎓',
    title: '25세 사회초년생',
    label: '적립 시작 · 성장형',
    desc:  '월 50만원 적립 · 자산 500만 · 장기 복리',
    form:  {
      age: 25, monthly_invest: 50, reserve: 500,
      monthly_target: 200, risk_tolerance: 'aggressive', invest_growth: 7,
    },
  },
  {
    key:   'age35',
    icon:  '👩‍💼',
    title: '35세 직장인',
    label: '자산 형성 · 균형형',
    desc:  '월 100만원 적립 · 자산 5천만 · 45세 목표',
    form:  {
      age: 35, monthly_invest: 100, reserve: 5000,
      monthly_target: 200, risk_tolerance: 'moderate', invest_growth: 5,
    },
  },
  {
    key:   'age45',
    icon:  '👨‍👩‍👧',
    title: '45세 중년 가장',
    label: '노후 준비 본격 · 균형형',
    desc:  '월 150만원 적립 · 자산 2억 · 본인+자녀',
    form:  {
      age: 45, monthly_invest: 150, reserve: 20000,
      monthly_target: 250, risk_tolerance: 'moderate', invest_growth: 3,
    },
  },
  {
    key:   'age60',
    icon:  '👴',
    title: '60세 은퇴자',
    label: '인출 · 안정형',
    desc:  '자산 5억 · 즉시 월 200만원 인출',
    form:  {
      age: 60, monthly_invest: 0, reserve: 50000,
      monthly_target: 200, risk_tolerance: 'conservative', invest_growth: 0,
    },
  },
]

// ── SHAP 지표 → 3단계 설명 (지표 → 의미 → 배당 영향) ──────────────────
const SHAP_3STEP = {
  payout_ratio: {
    safe: { label: '배당성향', metric: '이익 대비 배당 비율이 낮음', meaning: '회사가 이익 중 일부만 배당에 쓰고 나머지를 유보합니다', impact: '수익이 일시 감소해도 배당을 유지할 여력이 충분합니다' },
    risk: { label: '배당성향', metric: '이익 대비 배당 비율이 높음', meaning: '이익 대부분을 배당으로 지급해 회사에 유보금이 부족합니다', impact: '수익이 소폭만 줄어도 배당 삭감 가능성이 높아집니다' },
  },
  dividend_coverage: {
    safe: { label: '배당커버리지', metric: '현금흐름이 배당의 2배 이상', meaning: '현재 배당금보다 실제 벌어들이는 현금이 훨씬 많습니다', impact: '단기적으로 배당을 삭감할 이유가 없는 안정적 상태입니다' },
    risk: { label: '배당커버리지', metric: '현금흐름이 배당에 못 미침', meaning: '번 돈보다 배당으로 나가는 돈이 많아 재정 부담이 있습니다', impact: '현금 부족 시 배당 삭감이 불가피할 수 있습니다' },
  },
  fcf: {
    safe: { label: '잉여현금흐름', metric: 'FCF 플러스 — 현금 창출 중', meaning: '설비투자 후에도 남는 현금이 있어 배당 재원이 충분합니다', impact: '배당 유지·증가 여력이 있고 부채 없이 배당 가능합니다' },
    risk: { label: '잉여현금흐름', metric: 'FCF 마이너스 — 현금 소진 중', meaning: '투자 비용이 영업 수익을 초과해 외부 자금이 필요합니다', impact: '배당을 유지하려면 차입에 의존해야 해 삭감 위험이 높습니다' },
  },
  operating_cf: {
    safe: { label: '영업현금흐름', metric: '영업 현금 창출 양호', meaning: '본업에서 꾸준히 현금을 벌어들이고 있습니다', impact: '배당 원천이 안정적이라 지속 가능성이 높습니다' },
    risk: { label: '영업현금흐름', metric: '영업 현금흐름 감소', meaning: '최근 영업활동으로 벌어들이는 현금이 줄고 있습니다', impact: '현금흐름 악화는 향후 배당 유지 능력을 약화시킬 수 있습니다' },
  },
  div_to_ocf: {
    safe: { label: '영업현금 대비 배당', metric: '배당이 영업현금의 50% 이하', meaning: '영업으로 번 돈 중 절반 이하만 배당에 씁니다', impact: '배당이 과중하지 않아 지속 가능성이 높습니다' },
    risk: { label: '영업현금 대비 배당', metric: '배당이 영업현금의 80% 초과', meaning: '영업으로 번 돈 대부분을 배당에 소진합니다', impact: '영업이 조금만 악화돼도 배당 재원이 부족해집니다' },
  },
  dps_yoy_pct: {
    safe: { label: '주당배당금 변화', metric: '배당금 전년 대비 증가·유지', meaning: '최근 실제로 배당금을 올리거나 유지하고 있습니다', impact: '배당성장 의지가 확인되어 향후 증배 가능성이 높습니다' },
    risk: { label: '주당배당금 변화', metric: '배당금 전년 대비 감소', meaning: '최근 배당금을 실제로 줄인 이력이 있습니다', impact: '추가 삭감 가능성이 있어 주의가 필요합니다' },
  },
  ocf_to_capex: {
    safe: { label: '설비투자 대비 현금', metric: '설비투자 후 현금 여유 있음', meaning: '설비에 투자하고도 충분한 현금이 남습니다', impact: '투자와 배당을 동시에 유지할 수 있는 재무 구조입니다' },
    risk: { label: '설비투자 대비 현금', metric: '설비투자 부담이 큼', meaning: '설비 유지에 많은 현금이 소요되어 여유가 적습니다', impact: '배당보다 설비투자를 우선할 경우 배당이 줄 수 있습니다' },
  },
  fcf_negative: {
    safe: { label: '잉여현금흐름', metric: 'FCF 플러스', meaning: '현금을 벌어들이고 있어 배당 재원이 있습니다', impact: '외부 차입 없이 배당 지급 가능합니다' },
    risk: { label: '잉여현금흐름', metric: 'FCF 마이너스', meaning: '현금이 소진되고 있어 배당 재원이 부족합니다', impact: '차입 또는 자산 매각 없이는 배당 유지가 어렵습니다' },
  },
  capex: {
    safe: { label: '설비투자', metric: '설비투자 안정적', meaning: '매년 비슷한 수준의 설비 투자가 이루어집니다', impact: '예측 가능한 투자로 배당 계획이 안정적입니다' },
    risk: { label: '설비투자', metric: '설비투자 급증', meaning: '최근 대규모 투자 집행으로 현금이 빠르게 소진됩니다', impact: '투자 완료까지 배당 여력이 일시적으로 줄어들 수 있습니다' },
  },
}
function shapReadout(factors) {
  return (factors || []).slice(0, 3).map(f => {
    const p = SHAP_3STEP[f.feature]
    if (!p) return null
    const side = f.direction === '안전' ? p.safe : p.risk
    return { ...side, direction: f.direction }
  }).filter(Boolean)
}
// ── 현실 맥락: 이 종목이 현실에서 어떤 종목인가 (섹터 기반) ──
function realWorldContext(name = '') {
  const n = String(name)
  if (/메리츠/.test(n))                 return '손해보험 대표주. 보험업은 현금흐름이 안정적이라 국내 고배당·장기 보유 투자자가 선호하는 종목입니다.'
  if (/코리안리/.test(n))               return '국내 유일 전업 재보험사. 안정적 수익 기반으로 꾸준한 배당을 지급해 고배당 포트폴리오에 자주 담깁니다.'
  if (/화재|손해|보험|생명/.test(n))    return '보험 섹터 — 안정적 현금흐름과 꾸준한 배당으로 국내 고배당 투자자가 장기 보유합니다.'
  if (/포스코|인터내셔널|상사/.test(n)) return '종합상사(에너지·식량 트레이딩). 실적 성장과 배당 확대가 병행되는 배당성장주로 분류됩니다.'
  if (/지주|금융|은행|증권|카드/.test(n)) return '금융 섹터 — 규제 자본 내에서 안정적 배당을 지급하는 국내 대표 고배당 업종입니다.'
  if (/동서|식품|음료|제과/.test(n))    return '필수소비재(식음료) — 경기 방어적이고 배당이 꾸준해 안정형 투자자가 선호합니다.'
  return '국내 배당지수(KRX 고배당) 구성 종목 — 배당 매력으로 포트폴리오에 편입되었습니다.'
}

// ── 종목별 현실 투자 맥락 설명 ──────────────────────────────────
// "무엇인지 · 왜 선택했는지 · 어떤 투자자가 사용하는지"
function getStockDescription(r) {
  const t = r.ticker || ''
  const n = r.name || ''
  // 미국 대표 ETF/종목
  if (t === 'SCHD') return '미국 대표 배당성장 ETF. 배당 성장과 자본차익을 동시에 추구합니다. 장기 투자자들이 핵심 자산으로 활용하는 ETF입니다.'
  if (t === 'VYM')  return '뱅가드 고배당 ETF. 높은 배당수익률과 폭넓은 분산을 제공합니다. 안정적 현금흐름을 원하는 투자자가 선호합니다.'
  if (t === 'DGRO') return '블랙록 배당성장 ETF. 배당을 꾸준히 늘려온 기업에 투자합니다. 장기 복리 효과를 극대화하려는 투자자에게 적합합니다.'
  if (t === 'VIG')  return '뱅가드 배당성장 ETF. 10년 이상 연속 증배 기업만 편입합니다. 배당 안정성이 최우선인 보수적 투자자가 활용합니다.'
  if (t === 'JEPI') return 'JP모간 커버드콜 ETF. 매월 높은 현금흐름을 제공합니다. 은퇴 후 즉시 소득이 필요한 투자자에게 특히 유용합니다.'
  if (t === 'JEPQ') return 'JP모간 나스닥 커버드콜 ETF. 기술주 성장성과 높은 월배당을 결합합니다. 성장과 현금흐름을 동시에 원하는 투자자가 선택합니다.'
  if (t === 'SPYD') return 'S&P500 고배당 ETF. 고배당 종목 80개를 균등 비중으로 투자합니다. 단순하고 높은 배당수익률을 원하는 투자자용입니다.'
  if (t === 'HDV')  return '블랙록 고배당 ETF. 재무 건전성이 높은 고배당 기업을 선별합니다. 안정성을 중시하는 보수적 투자자가 선호합니다.'
  if (t === 'NOBL') return 'S&P500 배당귀족 ETF. 25년 이상 연속 증배한 기업만 편입합니다. 배당 신뢰성이 검증된 최고 등급 기업에 투자합니다.'
  if (t === 'QYLD') return '나스닥 커버드콜 ETF. 월배당으로 높은 현금흐름을 제공합니다. 자본차익보다 즉각적 현금흐름이 필요한 투자자에게 적합합니다.'
  if (t === 'O')    return '미국 대표 월배당 리츠(Realty Income). 매달 배당을 지급하는 유일한 S&P500 리츠입니다. 은퇴 준비 및 현금흐름 투자자들이 핵심 자산으로 활용합니다.'
  if (t === 'VNQ')  return '뱅가드 미국 리츠 ETF. 상업용 부동산 전체에 분산 투자합니다. 인플레이션 방어와 안정적 배당을 동시에 원하는 투자자가 활용합니다.'
  if (t === 'TLT')  return '미국 20년 장기국채 ETF. 시장 위기 시 방어 역할을 합니다. 변동성 완화와 포트폴리오 안정화를 위해 일부 편입합니다.'
  if (t === 'BND' || t === 'AGG') return '미국 채권 ETF. 주식 하락 시 손실을 완충합니다. 보수적 투자자의 안전 자산 역할을 합니다.'
  if (t === 'KO')   return '코카콜라 — 60년 이상 연속 증배한 배당귀족주입니다. 경기 방어적 소비재로 배당 신뢰성이 최고 수준입니다.'
  if (t === 'JNJ')  return '존슨앤존슨 — 60년 이상 연속 증배한 헬스케어 배당귀족입니다. 안정적 현금흐름과 높은 배당 신뢰성으로 장기 보유에 적합합니다.'
  if (t === 'PG')   return '프록터앤갬블 — 생활용품 글로벌 1위 기업으로 67년 연속 증배합니다. 경기 불황에도 수요가 유지되는 최고 안정형 배당주입니다.'
  if (t === 'ABBV') return '애브비 — 고배당 제약사로 배당수익률과 성장성을 동시에 제공합니다. 헬스케어 섹터 현금흐름을 원하는 투자자가 선호합니다.'
  if (t === 'MCD')  return '맥도날드 — 글로벌 프랜차이즈 로열티 기반 안정 수익 구조입니다. 경기 방어적이며 장기 배당성장 이력이 탁월합니다.'
  // 국내 종목 — realWorldContext 활용
  if (/^\d{6}$/.test(t)) return realWorldContext(n)
  return null
}

// ── SHAP 배당 삭감 예측 근거 패널 (XAI) ──────────────────────
// 추천 종목 중 한국 개별주(6자리 코드)를 골라 /explain 호출 →
// 삭감 위험확률 + 지표별 기여 + AI 설명 + 현실 맥락.
function ShapExplainPanel({ recs }) {
  const krStocks = useMemo(
    () => (recs || []).filter(r => r.asset_class === 'kr_stock' && /^\d{6}$/.test(String(r.ticker || ''))),
    [recs],
  )
  const [sel, setSel]         = useState('')
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr]         = useState(null)

  useEffect(() => { if (krStocks.length) setSel(s => s || krStocks[0].ticker) }, [krStocks])
  useEffect(() => {
    if (!sel) return
    let alive = true
    setLoading(true); setErr(null)
    api.get(`/api/stock/${sel}/explain`)
      .then(r => { if (alive) setData(r.data) })
      .catch(() => { if (alive) setErr('이 종목의 예측 근거 데이터를 불러올 수 없습니다.') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [sel])

  if (!krStocks.length) return null
  const factors = data?.top_risk_factors || []
  const prob    = data?.cut_prob ?? null
  const probCol = prob >= 70 ? '#dc2626' : prob >= 40 ? '#d97706' : '#059669'
  const selName = (krStocks.find(r => String(r.ticker) === String(sel)) || {}).name || ''
  const aiLines = shapReadout(factors)

  return (
    <div id="sec-shap" className="card" style={{ scrollMarginTop: 16 }}>
      <h3 className="card-title">
        🧠 배당 삭감 예측 근거 (XAI · SHAP)
        <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--text-sub,#64748b)', marginLeft: 8 }}>
          모델이 “왜 위험한가”를 재무 지표별로 설명
        </span>
      </h3>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '8px 0 14px' }}>
        <span style={{ fontSize: 13, color: 'var(--text-sub,#64748b)' }}>종목 선택</span>
        <select value={sel} onChange={e => setSel(e.target.value)}
          style={{ padding: '6px 10px', borderRadius: 8, border: '1px solid #d1d5db', fontSize: 13 }}>
          {krStocks.map(r => <option key={r.ticker} value={r.ticker}>{r.name} ({r.ticker})</option>)}
        </select>
      </div>

      {loading && <div style={{ fontSize: 13, color: 'var(--text-sub,#64748b)' }}>분석 중…</div>}
      {err && <div style={{ fontSize: 13, color: '#dc2626' }}>{err}</div>}

      {data && !loading && (
        <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
            <span style={{ fontSize: 34, fontWeight: 800, color: probCol }}>{prob}%</span>
            <span style={{ fontSize: 13, color: 'var(--text-sub,#64748b)' }}>
              배당 삭감 위험확률 · 위험도 <b style={{ color: probCol }}>{data.risk_level}</b>
            </span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {factors.map((f, i) => {
              const isRisk = f.direction === '위험 증가'
              const w = f.impact === 'high' ? 100 : f.impact === 'medium' ? 66 : 38
              const barCol = isRisk ? '#ef4444' : '#22c55e'
              return (
                <div key={i} style={{ display: 'grid', gridTemplateColumns: '150px 1fr 120px', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 12.5, color: 'var(--text,#1f2937)' }}>{f.label}</span>
                  <div style={{ height: 14, background: '#eef1f5', borderRadius: 7, overflow: 'hidden' }}>
                    <div style={{ width: `${w}%`, height: '100%', background: barCol, borderRadius: 7 }} />
                  </div>
                  <span style={{ fontSize: 12, textAlign: 'right', color: isRisk ? '#b91c1c' : '#15803d', fontWeight: 600 }}>
                    {f.display_label ?? f.value}{f.unit} {isRisk ? '위험↑' : '안전'}
                  </span>
                </div>
              )
            })}
          </div>

          {/* AI 설명 — 3단계: 지표 → 의미 → 배당 영향 */}
          {aiLines.length > 0 && (
            <div style={{ marginTop: 14 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#1456f0', marginBottom: 8 }}>🤖 AI 설명 — 지표 · 의미 · 배당 영향</div>
              {aiLines.map((step, i) => (
                <div key={i} style={{
                  marginBottom: 12, padding: '10px 12px',
                  background: step.direction === '안전' ? 'rgba(5,150,105,.04)' : 'rgba(220,38,38,.04)',
                  borderLeft: `3px solid ${step.direction === '안전' ? '#059669' : '#ef4444'}`,
                  borderRadius: '0 8px 8px 0',
                }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: step.direction === '안전' ? '#059669' : '#dc2626', marginBottom: 4 }}>
                    {step.label} — {step.metric}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text,#283143)', lineHeight: 1.6, marginBottom: 3 }}>
                    <span style={{ fontWeight: 600 }}>의미:</span> {step.meaning}
                  </div>
                  <div style={{ fontSize: 12, color: step.direction === '안전' ? '#059669' : '#b91c1c', fontWeight: 600 }}>
                    → 배당 영향: {step.impact}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* 현실 맥락 — 현실에서 이 종목은 */}
          <div style={{ marginTop: 12, background: '#f4f6f9', borderRadius: 8, padding: '9px 12px' }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--border)', marginBottom: 3 }}>🏢 현실에서 이 종목은</div>
            <div style={{ fontSize: 12.5, color: 'var(--text,#1f2937)', lineHeight: 1.55 }}>{realWorldContext(selName)}</div>
          </div>

          {data.summary && (
            <div style={{ marginTop: 10, fontSize: 12.5, color: 'var(--text-muted,#475569)' }}>💡 {data.summary}</div>
          )}
          <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-muted,#cbd5e1)' }}>
            Survival 리스크 모델 · 막대 길이 = 피처 기여 강도(high/medium/low) · 출처: DART 재무 데이터
          </div>
        </>
      )}
    </div>
  )
}

export default function Portfolio() {
  const [form, setForm] = useState({
    age:            40,
    monthly_invest: 100,
    reserve:        5000,
    monthly_target: 100,
    risk_tolerance: 'moderate',
    invest_growth:  5,        // 적립금 연 증가율(%) — 소득 상승 반영
  })
  const [result,    setResult]    = useState(null)
  const [loading,   setLoading]   = useState(false)
  const [error,     setError]     = useState(null)
  const [activePersona, setActivePersona] = useState(null)
  const [showAnalysis, setShowAnalysis] = useState(false)   // 상세 분석 접기/펼치기
  const [showAllHoldings, setShowAllHoldings] = useState(false)  // 포트폴리오 전체 보기
  const [resultLoaded, setResultLoaded] = useState(false)        // 저장본 불러온 결과 여부

  // ── 사용자 인증 상태 ──────────────────────────────────────
  const [authEmail, setAuthEmail] = useState(auth.getEmail())
  const [authOpen,  setAuthOpen]  = useState(false)
  const [authMode,  setAuthMode]  = useState('login')  // 'login' | 'register'
  const [authForm,  setAuthForm]  = useState({ email: '', password: '' })
  const [authMsg,   setAuthMsg]   = useState('')
  const [myList,    setMyList]    = useState([])
  const [myOpen,    setMyOpen]    = useState(false)
  const [saveMsg,   setSaveMsg]   = useState('')
  const [showAssumptions, setShowAssumptions] = useState(false)  // 계산 가정 요약 토글
  // 로그인 게이트: 로그인했거나 "둘러보기"를 누르면 통과. 로그인 없이도 모든 기능 사용 가능.
  const [entered,   setEntered]   = useState(auth.isLoggedIn())

  const refreshMyList = async () => {
    if (!auth.isLoggedIn()) return
    try { setMyList(await auth.myPortfolios()) } catch { /* 무시 */ }
  }
  // 최초 마운트: 이미 로그인 상태면 '목록만' 불러옴 (저장본 자동 표시 안 함 — 사용자가 직접 '불러오기')
  useEffect(() => {
    if (!auth.isLoggedIn()) return
    (async () => {
      try {
        setMyList(await auth.myPortfolios())
      } catch { /* 무시 */ }
    })()
  }, [])

  const handleAuth = async () => {
    setAuthMsg('')
    try {
      const fn = authMode === 'login' ? auth.login : auth.register
      const r = await fn(authForm.email, authForm.password)
      setAuthEmail(r.email); setAuthOpen(false); setEntered(true); setAuthForm({ email: '', password: '' })
      // 로그인 시 '내 포트폴리오 목록'만 불러옴 (저장본은 사용자가 직접 '불러오기'를 눌러야 표시)
      try {
        setMyList(await auth.myPortfolios())
      } catch { /* 무시 */ }
    } catch (e) {
      setAuthMsg(e?.response?.data?.detail || '실패했습니다. 다시 시도하세요.')
    }
  }

  const handleLogout = () => { auth.logout(); setAuthEmail(''); setMyList([]); setMyOpen(false) }

  const handleSavePortfolio = async () => {
    if (!result) return
    if (!auth.isLoggedIn()) { setAuthOpen(true); return }
    setSaveMsg('')
    try {
      const name = `${result.input?.age ?? form.age}세 · 목표 ${result.monthly_target}만원 · ${new Date().toLocaleDateString()}`
      // 변화 추적용 메타(프론트 계산값)를 payload에 첨부
      const monthlyDiv = (result.recommendations || []).reduce((s, r) => s + (r.est_monthly_div_after_tax || 0), 0)
      const payload = { ...result, _meta: {
        achieve_age: achieveAge ? Math.ceil(achieveAge) : (mc?.p50Age ? Math.ceil(mc.p50Age) : null),
        monthly_div: Math.round(monthlyDiv * 10) / 10,
      } }
      await auth.savePortfolio(name, payload)
      setSaveMsg('✓ 저장됨')
      refreshMyList()
      setTimeout(() => setSaveMsg(''), 2500)
    } catch (e) {
      setSaveMsg(e?.response?.data?.detail || '저장 실패')
    }
  }

  const handleLoadSaved = async (id) => {
    try {
      const item = await auth.getSaved(id)
      setResultLoaded(true)
      setResult(item.payload)
      setMyOpen(false)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch { setSaveMsg('불러오기 실패') }
  }

  const handleDeleteSaved = async (id) => {
    try { await auth.deleteSaved(id); refreshMyList() } catch { /* 무시 */ }
  }

  const handleChange = (key, val) => {
    setForm(f => ({ ...f, [key]: val }))
    setActivePersona(null)  // 수동 변경 시 페르소나 표시 해제
  }

  // 단일 진실의 원천: form override를 받을 수 있게
  const runRecommend = async (overrideForm) => {
    const f = overrideForm || form
    setLoading(true); setError(null)
    try {
      // investable_amount = 초기 여유자금(reserve)만. monthly_invest는 monthly_savings로 별도 전달.
      // reserve=0이면 백엔드가 target_yield=5%로 폴백하고 양호하게 처리함.
      const investable = Number(f.reserve)
      const res = await api.post('/api/portfolio/recommend', {
        age:               Number(f.age),
        annual_income:     Number(f.monthly_invest) * 12,  // ISA 유형 판단용 근사치
        monthly_target:    Number(f.monthly_target),
        investable_amount: investable,
        risk_tolerance:    f.risk_tolerance,
        monthly_savings:   Number(f.monthly_invest),
        savings_growth:    Number(f.invest_growth ?? 0),
      })
      setResultLoaded(false)
      setResult({
        ...res.data,
        monthly_invest: Number(f.monthly_invest),
        reserve:        Number(f.reserve),
        age:            Number(f.age),
        monthly_target: Number(f.monthly_target),
        invest_growth:  Number(f.invest_growth ?? 0),
      })
      // 데모 모드 또는 모든 분석 결과 → 상세 분석 자동 펼침
      setShowAnalysis(true)
    } catch (err) {
      console.error('API 오류:', err)
      const msg = err?.response?.data?.detail || err?.message || '알 수 없는 오류'
      setError(`서버 연결 실패. FastAPI 서버를 확인하세요. (${msg})`)
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
          mc, portfolioInsight, fireTargets, growthScenarios, investScenarios } = useMemo(() => {
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
      avgYield, result.age, result.monthly_target, atYield, result.invest_growth || 0,
    )

    // Monte Carlo: 1000회 시뮬레이션
    const mc = runMonteCarlo(
      result.monthly_invest, result.reserve,
      avgYield, atYield, result.age, result.monthly_target, recs, 1000, result.invest_growth || 0,
    )

    // AI 포트폴리오 설명
    const insight = generatePortfolioInsight(
      recs, result, mc.achieveProb, mc.p50Age, result.risk_alerts,
    )

    // FIRE 달성 나이 — 헤드라인과 동일 엔진(프론트·증액 반영)으로 통일
    const g = result.invest_growth || 0
    const fireTargets = [
      { name: '배당 목표', icon: '🎯', target: Number(result.monthly_target) },
      { name: 'Lean FIRE', icon: '🏠', target: 120 },
      { name: '일반 FIRE', icon: '🌴', target: 250 },
    ].map(t => {
      const r = calcCompoundGrowth(result.monthly_invest, result.reserve, avgYield,
                                   result.age, t.target, atYield, g)
      return { ...t, age: r.achieveAge ? Math.ceil(r.achieveAge) : null }
    })

    // 적립 증가율별 '배당 목표' 달성 나이 — "승진하면 몇 년 빨라지나"
    const growthScenarios = [0, 3, 5, 7].map(gr => {
      const r = calcCompoundGrowth(result.monthly_invest, result.reserve, avgYield,
                                   result.age, Number(result.monthly_target), atYield, gr)
      return { gr, age: r.achieveAge ? Math.ceil(r.achieveAge) : null }
    })

    // 투자금 증가 시나리오 — "얼마씩 더 투자하면 몇 살에 달성하나"
    const baseInvest = result.monthly_invest || 0
    const investScenarios = [0, 10, 20, 30].map(extra => {
      const r2 = calcCompoundGrowth(baseInvest + extra, result.reserve, avgYield,
                                    result.age, Number(result.monthly_target), atYield, g)
      return { extra, monthlyInvest: baseInvest + extra, age: r2.achieveAge ? Math.ceil(r2.achieveAge) : null }
    })

    return {
      compoundData: data, achieveAge, afterTaxYield: atYield,
      cashflowData: cashflow, mc, portfolioInsight: insight, fireTargets, growthScenarios, investScenarios,
    }
  }, [result])

  // 도넛 데이터 (자산군별 색상)
  const donutData = result?.recommendations?.map(r => ({
    name:   r.name,
    value:  r.weight_pct,
    color:  ASSET_COLOR[r.asset_class] || '#2563eb',
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

  // ── 로그인 게이트 화면 (로그인 없이도 "둘러보기"로 바로 사용 가능) ──
  if (!entered) {
    return (
      <div style={{
        minHeight: 'calc(100vh - 60px)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'var(--bg, #f6f8fb)', padding: 20,
      }}>
        <div className="card" style={{ width: '100%', maxWidth: 420, padding: 32, textAlign: 'center' }}>
          <div style={{ fontSize: 30, marginBottom: 8 }}>📈</div>
          <h2 style={{ margin: '0 0 4px', fontSize: 22, color: 'var(--text, #1f2937)' }}>AI Cashflow OS</h2>
          <div style={{ fontSize: 13, color: 'var(--text-sub, #64748b)', marginBottom: 22 }}>
            배당 삭감 예측 기반 소득 지속성 분석 시스템
          </div>

          <input type="email" placeholder="이메일" value={authForm.email}
            onChange={(e) => setAuthForm(f => ({ ...f, email: e.target.value }))}
            onKeyDown={(e) => { if (e.key === 'Enter') handleAuth() }}
            style={{ width: '100%', padding: '11px 12px', marginBottom: 8, borderRadius: 8, border: '1px solid #d1d5db', fontSize: 14, boxSizing: 'border-box' }} />
          <input type="password" placeholder="비밀번호 (4자 이상)" value={authForm.password}
            onChange={(e) => setAuthForm(f => ({ ...f, password: e.target.value }))}
            onKeyDown={(e) => { if (e.key === 'Enter') handleAuth() }}
            style={{ width: '100%', padding: '11px 12px', marginBottom: 8, borderRadius: 8, border: '1px solid #d1d5db', fontSize: 14, boxSizing: 'border-box' }} />
          {authMsg && <div style={{ fontSize: 12, color: '#dc2626', marginBottom: 8 }}>{authMsg}</div>}

          <button type="button" onClick={handleAuth}
            style={{ width: '100%', padding: '11px', borderRadius: 8, border: 'none', background: '#1456f0', color: '#fff', fontWeight: 700, fontSize: 15, cursor: 'pointer' }}>
            {authMode === 'login' ? '로그인' : '가입하기'}
          </button>

          <div style={{ fontSize: 13, color: 'var(--text-sub, #64748b)', margin: '12px 0' }}>
            {authMode === 'login' ? '계정이 없으신가요? ' : '이미 계정이 있으신가요? '}
            <button type="button" onClick={() => { setAuthMode(m => m === 'login' ? 'register' : 'login'); setAuthMsg('') }}
              style={{ background: 'none', border: 'none', color: '#1456f0', fontWeight: 600, cursor: 'pointer', fontSize: 13 }}>
              {authMode === 'login' ? '회원가입' : '로그인'}
            </button>
          </div>

          <div style={{ borderTop: '1px solid #eef1f5', paddingTop: 14 }}>
            <button type="button" onClick={() => setEntered(true)}
              style={{ width: '100%', padding: '11px', borderRadius: 8, border: '1px solid #d1d5db', background: '#fff', color: 'var(--border)', fontWeight: 600, fontSize: 14, cursor: 'pointer' }}>
              로그인 없이 둘러보기 →
            </button>
            <div style={{ fontSize: 11.5, color: 'var(--text-muted, #cbd5e1)', marginTop: 8 }}>
              로그인하지 않아도 모든 분석 기능을 사용할 수 있습니다. 로그인하면 포트폴리오 저장·변화 추적이 가능합니다.
            </div>
          </div>
        </div>
      </div>
    )
  }

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

        {/* 사용자 인증 바 */}
        <div style={{ marginTop: 10, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {authEmail ? (
            <>
              <span style={{ fontSize: 13, color: 'var(--text-sub)' }}>👤 {authEmail}</span>
              <button type="button" onClick={() => { setMyOpen(o => !o); refreshMyList() }}
                style={authBtn(false)}>📁 내 포트폴리오 {myList.length ? `(${myList.length})` : ''}</button>
              <button type="button" onClick={handleLogout} style={authBtn(false)}>로그아웃</button>
            </>
          ) : (
            <button type="button" onClick={() => { setAuthMode('login'); setAuthOpen(true) }}
              style={authBtn(true)}>🔑 로그인 / 회원가입</button>
          )}
        </div>

        {/* 내 포트폴리오 목록 패널 */}
        {authEmail && myOpen && (
          <div className="card" style={{ marginTop: 10 }}>
            <h3 className="card-title" style={{ fontSize: 15 }}>📁 내 포트폴리오</h3>
            {myList.length === 0 ? (
              <div style={{ fontSize: 13, color: 'var(--text-sub)' }}>저장된 포트폴리오가 없습니다. 추천 결과에서 "💾 저장"을 눌러보세요.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {myList.map(p => (
                  <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                       padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 8 }}>
                    <div style={{ flex: 1, minWidth: 180 }}>
                      <div style={{ fontSize: 13, fontWeight: 600 }}>{p.name}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-sub)' }}>
                        건강도 {p.summary?.health_score ?? '-'} · 생존 {p.summary?.survival ?? '-'}%
                      </div>
                    </div>
                    <button type="button" onClick={() => handleLoadSaved(p.id)} style={authBtn(true)}>불러오기</button>
                    <button type="button" onClick={() => handleDeleteSaved(p.id)}
                      style={{ ...authBtn(false), color: '#dc2626' }}>삭제</button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 로그인/회원가입 모달 */}
      {authOpen && (
        <div onClick={() => setAuthOpen(false)} style={{ position: 'fixed', inset: 0, zIndex: 50,
             background: 'rgba(15,23,42,.45)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div onClick={e => e.stopPropagation()} className="card"
               style={{ width: 340, maxWidth: '90vw' }}>
            <h3 className="card-title">{authMode === 'login' ? '🔑 로그인' : '📝 회원가입'}</h3>
            <input type="email" placeholder="이메일" value={authForm.email}
              onChange={e => setAuthForm(f => ({ ...f, email: e.target.value }))}
              style={modalInput} />
            <input type="password" placeholder="비밀번호 (4자 이상)" value={authForm.password}
              onChange={e => setAuthForm(f => ({ ...f, password: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && handleAuth()}
              style={modalInput} />
            {authMsg && <div style={{ fontSize: 12, color: '#dc2626', marginTop: 6 }}>{authMsg}</div>}
            <button type="button" onClick={handleAuth} className="btn btn-primary"
              style={{ width: '100%', marginTop: 12 }}>
              {authMode === 'login' ? '로그인' : '가입하기'}
            </button>
            <div style={{ textAlign: 'center', marginTop: 10, fontSize: 12, color: 'var(--text-sub)' }}>
              {authMode === 'login' ? '계정이 없으신가요? ' : '이미 계정이 있으신가요? '}
              <span style={{ color: 'var(--blue)', cursor: 'pointer', fontWeight: 600 }}
                onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthMsg('') }}>
                {authMode === 'login' ? '회원가입' : '로그인'}
              </span>
            </div>
          </div>
        </div>
      )}

      <div className="portfolio-layout">
        {/* ── 입력 폼 ── */}
        <div className="card form-card">
          <h3 className="card-title">내 정보 입력</h3>

          {/* ── 발표 데모 버튼 (DEMO_RUNBOOK 고정 시나리오) ── */}
          <button
            type="button"
            onClick={() => handlePersonaClick(DEMO_PRESENTATION)}
            disabled={loading}
            style={{
              width: '100%', display: 'flex', alignItems: 'center', gap: 10,
              padding: '12px 16px', marginBottom: 8,
              background: activePersona === 'demo_presentation'
                ? 'rgba(139,92,246,.18)'
                : 'linear-gradient(135deg, rgba(139,92,246,.1) 0%, rgba(37,99,235,.08) 100%)',
              border: `2px solid ${activePersona === 'demo_presentation' ? '#7c3aed' : 'rgba(139,92,246,.4)'}`,
              borderRadius: 10, cursor: loading ? 'wait' : 'pointer',
              transition: 'all .2s',
            }}
          >
            <span style={{ fontSize: 22 }}>🎬</span>
            <div style={{ flex: 1, textAlign: 'left' }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
                발표 데모 시작
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-sub)', marginTop: 1 }}>
                {DEMO_PRESENTATION.label} — {DEMO_PRESENTATION.story}
              </div>
            </div>
            <span style={{
              fontSize: 10, padding: '2px 7px', borderRadius: 5, fontWeight: 700,
              background: '#7c3aed', color: '#fff',
            }}>
              {loading && activePersona === 'demo_presentation' ? '분석 중...' : '▶ 시작'}
            </span>
          </button>

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
              display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 6,
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
            <div className="field-hint">FIRE 예상 시점 · 생애주기 배당 분석에 사용됩니다</div>
          </div>

          <div className="form-group">
            <label>월 투자 금액 <span className="label-sub">매달 적립</span></label>
            <div className="input-wrap">
              <input type="number" value={form.monthly_invest}
                onChange={e => handleChange('monthly_invest', e.target.value)} step={10} min={0} />
              <span className="input-unit">만원</span>
            </div>
            <div className="field-hint">매월 추가로 투자할 금액 — 급여에서 저축하는 금액 기준</div>
          </div>

          <div className="form-group">
            <label>적립금 증가율 <span className="label-sub">소득 상승 반영 (연)</span></label>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
              {[{v:0,t:'고정'},{v:3,t:'보수 3%'},{v:5,t:'평균 5%'},{v:8,t:'고성장 8%'}].map(o => {
                const active = Number(form.invest_growth) === o.v
                return (
                  <button key={o.v} type="button" onClick={() => handleChange('invest_growth', o.v)}
                    style={{ padding: '7px 4px', fontSize: 12, fontWeight: 600, borderRadius: 8, cursor: 'pointer',
                      background: active ? 'rgba(37,99,235,.12)' : 'var(--surface2)',
                      border: `1px solid ${active ? 'var(--blue)' : 'var(--border)'}`,
                      color: active ? 'var(--blue)' : 'var(--text-sub)' }}>
                    {o.t}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="form-group">
            <label>초기 투자금 <span className="label-sub">현재 보유 자산</span></label>
            <div className="input-wrap">
              <input type="number" value={form.reserve}
                onChange={e => handleChange('reserve', e.target.value)} step={100} min={0} />
              <span className="input-unit">만원</span>
            </div>
            <div className="field-hint">지금 당장 투자에 넣을 수 있는 금액 — 예금·적금 해지 후 가능한 금액 포함, 없으면 0</div>
          </div>

          <div className="form-group">
            <label>목표 월 배당금</label>
            <div className="input-wrap">
              <input type="number" value={form.monthly_target}
                onChange={e => handleChange('monthly_target', e.target.value)} step={10} min={0} />
              <span className="input-unit">만원/월</span>
            </div>
            <div className="field-hint">배당만으로 받고 싶은 월 현금흐름 — 생활비 기준 입력 (예: 150~300만원)</div>
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
              position: 'fixed', left: 16, top: '50%',
              transform: 'translateY(-50%)',
              display: 'flex', flexDirection: 'column', gap: 2,
              padding: '12px 10px',
              background: '#ffffff',
              boxShadow: '0 4px 16px rgba(20,30,50,0.10)',
              border: '1px solid #e5e7eb',
              borderRadius: 12,
              zIndex: 50,
              maxHeight: '80vh', overflowY: 'auto',
            }}
          >
            <div style={{
              fontSize: 10, color: '#1456f0', fontWeight: 700,
              textTransform: 'uppercase', letterSpacing: 0.6,
              textAlign: 'center', marginBottom: 6,
            }}>
              빠른 이동
            </div>
            {RESULT_SECTIONS.map(s => (
              <a
                key={s.id}
                href={`#${s.id}`}
                onClick={(e) => {
                  e.preventDefault()
                  setShowAnalysis(true)   // 접혀 있으면 펼치고 이동
                  setTimeout(() => {
                    const el = document.getElementById(s.id)
                    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
                  }, 60)
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '6px 10px', borderRadius: 8,
                  fontSize: 11, color: 'var(--border)',
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

            {/* 발표 데모 시나리오 배너 */}
            {activePersona === 'demo_presentation' && (
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: '9px 14px', marginBottom: 10,
                background: 'linear-gradient(135deg, rgba(139,92,246,.1) 0%, rgba(37,99,235,.08) 100%)',
                border: '1px solid rgba(139,92,246,.35)',
                borderRadius: 10, fontSize: 12,
              }}>
                <span style={{ fontSize: 18 }}>🎬</span>
                <div style={{ flex: 1 }}>
                  <span style={{ fontWeight: 700, color: 'var(--text)' }}>발표 데모 시나리오 — </span>
                  <span style={{ color: 'var(--text-sub)' }}>
                    {DEMO_PRESENTATION.label} · {DEMO_PRESENTATION.story}
                  </span>
                </div>
              </div>
            )}

            {/* 저장 바 */}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, alignItems: 'center', marginBottom: 4 }}>
              {saveMsg && <span style={{ fontSize: 12, color: saveMsg.startsWith('✓') ? '#059669' : '#dc2626' }}>{saveMsg}</span>}
              <button type="button" onClick={handleSavePortfolio} style={authBtn(true)}>
                💾 {authEmail ? '이 포트폴리오 저장' : '로그인하고 저장'}
              </button>
            </div>

            {/* 🗺️ 결과 가이드 — 핵심 요약 + 다음 확인 섹션 안내 */}
            {(() => {
              const tgt   = Number(result.monthly_target) || 1
              const achAge = achieveAge ? Math.ceil(achieveAge) : (mc?.p50Age ? Math.ceil(mc.p50Age) : null)
              const prob  = mc?.achieveProb ?? 0
              const raCount = (result.risk_alerts || []).length
              const riskLevel = raCount === 0 ? { label: '낮음', color: '#059669' }
                : raCount <= 2      ? { label: '보통', color: '#d97706' }
                : { label: '높음', color: '#ef4444' }
              const scrollTo = (id) => {
                const el = document.getElementById(id)
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
              }
              return (
                <div style={{
                  background: 'var(--surface)', border: '1px solid var(--border)',
                  borderRadius: 10, padding: '12px 14px', marginBottom: 8, fontSize: 12.5,
                }}>
                  {/* 요약 한 줄 */}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 10, alignItems: 'center' }}>
                    <span style={{ fontWeight: 700, color: 'var(--text)', fontSize: 13 }}>📋 현재 분석 요약</span>
                    <span style={{ color: 'var(--text-sub)' }}>목표 {tgt}만원</span>
                    <span style={{ color: 'var(--text-sub)' }}>→</span>
                    <span style={{ fontWeight: 700, color: '#2563eb' }}>
                      {achAge ? `예상 ${achAge}세 달성` : '달성 시점 계산 중'}
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--text-muted, #94a3b8)',
                         background: 'rgba(148,163,184,.12)', borderRadius: 4, padding: '1px 5px' }}>
                      가정 기반 추정
                    </span>
                    <span style={{ color: 'var(--text-sub)', margin: '0 2px' }}>·</span>
                    <span style={{ color: 'var(--text-sub)' }}>달성 확률</span>
                    <span style={{ fontWeight: 700, color: prob >= 80 ? '#059669' : prob >= 50 ? '#d97706' : '#ef4444' }}>
                      {prob}%
                    </span>
                    <span style={{ color: 'var(--text-sub)', margin: '0 2px' }}>·</span>
                    <span style={{ color: 'var(--text-sub)' }}>배당 위험</span>
                    <span style={{ fontWeight: 700, color: riskLevel.color }}>{riskLevel.label}</span>
                  </div>
                  {/* 섹션 네비게이션 */}
                  <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
                    <div style={{
                      fontSize: 10.5, fontWeight: 700, color: 'var(--text-sub)',
                      textTransform: 'uppercase', letterSpacing: '.5px', marginBottom: 5,
                    }}>
                      다음으로 확인해보세요
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                      {[
                        { n: 1, text: '목표 달성 시점 확인', id: 'sec-headline' },
                        { n: 2, text: 'Monte Carlo로 변동 가능성 확인', id: 'sec-montecarlo' },
                        { n: 3, text: '목표 시점을 앞당기려면 FIRE 역산 시뮬레이터에서 조건 조정', id: 'sec-simulator' },
                      ].map(step => (
                        <button
                          key={step.n}
                          type="button"
                          onClick={() => scrollTo(step.id)}
                          style={{
                            display: 'flex', alignItems: 'center', gap: 7,
                            background: 'none', border: 'none', cursor: 'pointer',
                            padding: '2px 0', textAlign: 'left',
                          }}
                        >
                          <span style={{
                            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                            width: 17, height: 17, borderRadius: '50%',
                            background: 'rgba(37,99,235,.12)', color: '#2563eb',
                            fontSize: 10, fontWeight: 700, flexShrink: 0,
                          }}>{step.n}</span>
                          <span style={{ color: '#2563eb', fontSize: 12.5, textDecoration: 'underline', textDecorationColor: 'rgba(37,99,235,.3)' }}>
                            {step.text}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )
            })()}

            {/* ① 대시보드 헤드라인 — 목표·달성·진행률 한 카드 */}
            {(() => {
              const curAge = Number(result.input?.age ?? result.age ?? form.age)
              const achAge = achieveAge ? Math.ceil(achieveAge) : (mc?.p50Age ? Math.ceil(mc.p50Age) : null)
              const left = achAge ? achAge - curAge : null
              const fireTargetAge = Number(result.input?.target_fire_age) || 50
              const gap = achAge ? fireTargetAge - achAge : null
              const tgt = Number(result.monthly_target) || 1
              const curMonthly = (result.recommendations || []).reduce((s, r) => s + (r.est_monthly_div_after_tax || 0), 0)
              const prog = Math.min(100, curMonthly / tgt * 100)
              const netY = (afterTaxYield && afterTaxYield > 0) ? afterTaxYield : 4.0
              const targetAsset = (tgt * 12) / (netY / 100)            // 만원
              const curAsset = Number(result.monthly_invest || 0) * 12 + Number(result.reserve || 0)
              const fmt = (m) => m >= 10000 ? `${(m / 10000).toFixed(1)}억` : `${Math.round(m).toLocaleString()}만`
              const Box = ({ label, value, sub, big }) => (
                <div style={{ flex: 1, minWidth: 92, textAlign: 'center' }}>
                  <div style={{ fontSize: 11, color: 'var(--text-sub)' }}>{label}</div>
                  <div style={{ fontSize: big ? 38 : 20, fontWeight: 800, color: big ? '#2563eb' : 'var(--text)', lineHeight: 1.1 }}>{value}</div>
                  {sub && <div style={{ fontSize: 10.5, color: 'var(--text-sub)', marginTop: 2 }}>{sub}</div>}
                </div>
              )
              return (
                <div className="card" id="sec-headline" style={{ borderTop: '3px solid #2563eb' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                    <div style={{ fontSize: 13, color: 'var(--text-sub)', fontWeight: 700 }}>
                      🎯 목표 월배당 {tgt}만원 — 언제 도달하나
                    </div>
                    {gap != null && (
                      <div style={{ fontSize: 13, fontWeight: 800, padding: '4px 12px', borderRadius: 999,
                           background: gap >= 0 ? 'rgba(5,150,105,.12)' : 'rgba(220,38,38,.1)',
                           color: gap >= 0 ? '#059669' : '#dc2626' }}>
                        {gap > 0 ? `🎉 목표보다 ${gap}년 빠름` : gap === 0 ? `목표 시점에 정확히 달성` : `목표 대비 +${-gap}년`}
                      </div>
                    )}
                  </div>
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginTop: 10 }}>
                    <Box label="예상 달성" value={achAge ? `${achAge}세` : '미달성'} big
                         sub={achieveAge ? '복리 시뮬레이션 · 가정 기반 추정' : 'Monte Carlo P50 · 가정 기반 추정'} />
                    <Box label="현재 나이" value={`${curAge}세`} />
                    <Box label="남은 기간" value={left != null ? `${left}년` : '—'} />
                    <Box label="달성 확률" value={mc ? `${mc.achieveProb}%` : '—'} sub="적립 포함" />
                  </div>
                  <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-sub)',
                       background: 'var(--surface2)', borderRadius: 8, padding: '6px 10px' }}>
                    💰 현재 월 <b>{result.monthly_invest}만원</b> 투자
                    {result.invest_growth > 0 && ` · 연 ${result.invest_growth}% 증액`}
                    {' · '}배당 재투자 복리
                  </div>

                  {/* FIRE 진행률 — 원형 게이지 + 자산 바 */}
                  <div style={{ display: 'flex', gap: 20, alignItems: 'center', flexWrap: 'wrap', marginTop: 14 }}>
                    {(() => {
                      const R = 46, C = 2 * Math.PI * R
                      const pct = Math.max(0, Math.min(100, prog))
                      return (
                        <div style={{ position: 'relative', width: 120, height: 120 }}>
                          <svg width="120" height="120" style={{ transform: 'rotate(-90deg)' }}>
                            <circle cx="60" cy="60" r={R} fill="none" stroke="var(--surface2)" strokeWidth="11" />
                            <circle cx="60" cy="60" r={R} fill="none" stroke="#2563eb" strokeWidth="11"
                              strokeLinecap="round" strokeDasharray={C}
                              strokeDashoffset={C * (1 - pct / 100)} />
                          </svg>
                          <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column',
                               alignItems: 'center', justifyContent: 'center' }}>
                            <div style={{ fontSize: 26, fontWeight: 800, color: '#2563eb', lineHeight: 1 }}>{pct.toFixed(1)}%</div>
                            <div style={{ fontSize: 10, color: 'var(--text-sub)', marginTop: 2 }}>FIRE 진행도</div>
                          </div>
                        </div>
                      )
                    })()}
                    <div style={{ flex: 1, minWidth: 200 }}>
                      {(() => {
                        const lv = prog >= 100 ? { n: 6, t: 'FIRE 달성', c: '#7c3aed' }
                          : prog >= 75 ? { n: 5, t: 'FIRE 근접', c: '#2563eb' }
                          : prog >= 50 ? { n: 4, t: '경제적 독립 진입', c: '#059669' }
                          : prog >= 25 ? { n: 3, t: '성장기', c: '#059669' }
                          : prog >= 10 ? { n: 2, t: '새싹', c: '#d97706' }
                          : { n: 1, t: '현금흐름 씨앗', c: '#d97706' }
                        return (
                          <div style={{ display: 'inline-block', marginBottom: 8, fontSize: 12, fontWeight: 700,
                               padding: '3px 10px', borderRadius: 999, background: `${lv.c}1f`, color: lv.c }}>
                            LV.{lv.n} {lv.t}
                          </div>
                        )
                      })()}
                      <div style={{ fontSize: 13, marginBottom: 8 }}>
                        월배당 <b>{curMonthly.toFixed(1)}만</b> / 목표 <b>{tgt}만</b>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 4 }}>
                        <span style={{ color: 'var(--text-sub)' }}>목표 자산</span>
                        <span style={{ fontWeight: 700 }}>{fmt(curAsset)}원 → {fmt(targetAsset)}원 ({Math.min(100, curAsset / targetAsset * 100).toFixed(1)}%)</span>
                      </div>
                      <div style={{ height: 10, background: 'var(--surface2)', borderRadius: 5, overflow: 'hidden' }}>
                        <div style={{ width: `${Math.max(Math.min(100, curAsset / targetAsset * 100), 1)}%`, height: '100%', background: '#059669' }} />
                      </div>
                    </div>
                  </div>
                </div>
              )
            })()}

            {/* 계산 가정 요약 — 핵심 결과 카드 직후 (접기 가능) */}
            {(() => {
              const s   = result?.summary || {}
              const inp = result?.input   || {}

              // 수익률: result.summary 실제 API 응답값
              const divY   = (s.avg_dividend_yield_net ?? 0).toFixed(2)   // 역할A: 세후 배당수익률
              const totalY = (s.avg_total_return_net   ?? 0).toFixed(2)   // 역할B: 세후 총수익률
              const simY   = (s.avg_dividend_yield     ?? 0).toFixed(2)   // 복리 시뮬레이션 (세전 배당수익률)

              // CPI: 백엔드 실제 사용값 (cpi_rate_pct, 퍼센트 단위)
              const cpiRaw = result?.fire_plan?.cpi_rate_pct
                          ?? result?.reverse_fire?.cpi_rate_pct
                          ?? null
              // 단위 방어: 백엔드가 비율(0.025)로 보낼 경우 변환
              const cpi = cpiRaw != null
                ? (cpiRaw <= 1 ? (cpiRaw * 100).toFixed(1) : cpiRaw.toFixed(1))
                : '2.5'

              // 세율: tax_optimizer 실효세율 우선 → calcAfterTaxYield 역산 폴백
              const taxOpt = result?.tax_optimizer
              const effTaxStr = (() => {
                if (taxOpt?.effective_tax_rate_pct != null) {
                  return `${taxOpt.effective_tax_rate_pct.toFixed(1)}% (실효세율)`
                }
                // calcAfterTaxYield 역산: (avgYield - afterTaxYield) / avgYield × 100
                const aY = s.avg_dividend_yield || 0
                if (aY > 0 && afterTaxYield > 0) {
                  const impliedTax = ((aY - afterTaxYield) / aY * 100).toFixed(1)
                  return `약 ${impliedTax}% (계좌구성 추정)`
                }
                return '계좌별 상이 · 세금 최적화 결과 참조'
              })()

              const sg    = inp.savings_growth ?? 0
              const years = inp.target_fire_age && inp.age ? inp.target_fire_age - inp.age : '—'

              const assumptions = [
                {
                  label: '복리 시뮬레이션 수익률',
                  value: `${simY}%`,
                  note:  '이 화면 예상 달성 나이 계산 기준 (세전 배당수익률)',
                  tag:   '이 화면 복리',
                },
                {
                  label: '세후 배당수익률 (역할A)',
                  value: `${divY}%`,
                  note:  '공식 FIRE 목표 원금 역산 기준',
                  tag:   '서버 FIRE',
                },
                {
                  label: '세후 총수익률 (역할B)',
                  value: `${totalY}%`,
                  note:  '공식 FIRE 자산 누적 · 간이 추정 기준',
                  tag:   '서버·간이 추정',
                },
                {
                  label: 'CPI (물가상승률)',
                  value: `${cpi}%`,
                  note:  `공식 FIRE 목표 금액 조정 전용${cpiRaw == null ? ' · 기본값' : ' · 서버 실제값'} — 복리 시뮬레이션 미반영`,
                  tag:   '서버 FIRE 전용',
                  warn:  true,
                },
                {
                  label: '적립금 증가율',
                  value: sg > 0 ? `${sg}%/년` : '0% (고정)',
                  note:  sg > 0
                    ? '공식 FIRE 계산 반영 · 연말 인상 방식'
                    : '고정 — 실질 저축여력 감소 미반영',
                  tag:   '공식 FIRE 반영',
                },
                {
                  label: '포트폴리오 배당세율',
                  value: effTaxStr,
                  note:  taxOpt
                    ? '세금 최적화 엔진 산출 실효세율'
                    : '자산군·계좌 구성 기반 추정 · 절세계좌 별도 최적화',
                  tag:   '세후 계산',
                },
                {
                  label: '시뮬레이션 기간',
                  value: `${years}년`,
                  note:  `현재 ${inp.age ?? '?'}세 → 목표 FIRE ${inp.target_fire_age ?? '?'}세`,
                  tag:   '전체 공통',
                },
              ]

              return (
                <div style={{ marginBottom: 10 }}>
                  <button
                    type="button"
                    onClick={() => setShowAssumptions(v => !v)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 6,
                      background: 'none', border: 'none', cursor: 'pointer',
                      fontSize: 11, color: 'var(--text-sub)', padding: '4px 0',
                    }}
                  >
                    <span style={{
                      background: 'rgba(37,99,235,.08)', border: '1px solid rgba(37,99,235,.2)',
                      borderRadius: 5, padding: '2px 8px', fontWeight: 600, color: '#2563eb',
                    }}>
                      🔧 계산 가정 {showAssumptions ? '▲ 접기' : '▼ 보기'}
                    </span>
                    <span>각 섹션이 사용하는 수익률·CPI·기간 가정</span>
                  </button>

                  {showAssumptions && (
                    <div style={{
                      marginTop: 6, padding: '10px 14px',
                      background: 'var(--surface2)', borderRadius: 8,
                      border: '1px solid var(--border)',
                    }}>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 11, marginBottom: 10 }}>
                        {assumptions.map(item => (
                          <div key={item.label} style={{
                            minWidth: 160, flex: '1 1 160px',
                            padding: '7px 10px', background: 'var(--surface)',
                            borderRadius: 6,
                            border: item.warn
                              ? '1px solid rgba(245,158,11,.4)'
                              : '1px solid var(--border)',
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3, gap: 4 }}>
                              <span style={{ color: 'var(--text-sub)', fontSize: 10 }}>{item.label}</span>
                              <span style={{
                                fontSize: 9, padding: '1px 5px', borderRadius: 3, flexShrink: 0,
                                background: 'rgba(37,99,235,.08)', color: '#2563eb',
                              }}>{item.tag}</span>
                            </div>
                            <div style={{
                              fontWeight: 700, fontSize: 13,
                              color: item.warn ? '#d97706' : 'var(--text)',
                            }}>
                              {item.value}
                            </div>
                            <div style={{
                              color: 'var(--text-muted, #94a3b8)', fontSize: 9.5,
                              marginTop: 2, lineHeight: 1.4,
                            }}>
                              {item.note}
                            </div>
                          </div>
                        ))}
                      </div>
                      <div style={{
                        fontSize: 10, color: 'var(--text-muted, #94a3b8)',
                        paddingTop: 8, borderTop: '1px solid var(--border)', lineHeight: 1.6,
                      }}>
                        ※ 섹션마다 수익률 기준이 다릅니다. 배당 현금흐름과 자산 성장을 각각 다른 목적으로 분석하기 때문입니다.
                        결과는 가정 기반 추정치이며, 실제 시장 상황·세법 변경에 따라 달라질 수 있습니다.
                      </div>
                    </div>
                  )}
                </div>
              )
            })()}

            {/* ★ 목표 달성 근거 — "왜 N세인가" (항상 표시) */}
            {compoundData?.length > 1 && achieveAge && (() => {
              const fmt = (manwon) => manwon >= 10000
                ? `${(manwon / 10000).toFixed(1)}억` : `${Math.round(manwon).toLocaleString()}만`
              const targetAge = Math.ceil(achieveAge)
              const startAge = compoundData[0].age
              const picks = [...new Set([
                startAge,
                Math.round((startAge * 2 + targetAge) / 3),
                Math.round((startAge + targetAge * 2) / 3),
                targetAge,
              ])].filter(a => a >= startAge && a <= targetAge)
              const rows = picks.map(a =>
                compoundData.reduce((best, d) =>
                  Math.abs(d.age - a) < Math.abs(best.age - a) ? d : best, compoundData[0]))
              return (
                <div className="card" style={{ borderLeft: '3px solid #059669' }}>
                  <h3 className="card-title">📍 목표 달성 근거 — 왜 {targetAge}세인가?
                    <span className="title-sub">매년 적립·배당 재투자 복리 경로 (세후)</span>
                  </h3>
                  <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                      <thead>
                        <tr style={{ color: 'var(--text-sub)', fontSize: 12, textAlign: 'right' }}>
                          <th style={{ textAlign: 'left', padding: '6px 8px' }}>시점</th>
                          <th style={{ padding: '6px 8px' }}>누적 투자금</th>
                          <th style={{ padding: '6px 8px' }}>예상 자산</th>
                          <th style={{ padding: '6px 8px' }}>월 배당(세후)</th>
                        </tr>
                      </thead>
                      <tbody>
                        {rows.map((d, i) => {
                          const last = i === rows.length - 1
                          return (
                            <tr key={d.age} style={{ borderTop: '1px solid var(--border)',
                                 textAlign: 'right', fontWeight: last ? 700 : 400,
                                 background: last ? 'rgba(5,150,105,.06)' : 'transparent' }}>
                              <td style={{ textAlign: 'left', padding: '8px' }}>
                                {d.age}세 {i === 0 ? '(현재)' : last ? '🎯 달성' : ''}
                              </td>
                              <td style={{ padding: '8px', color: 'var(--text-sub)' }}>{fmt(d.invested)}원</td>
                              <td style={{ padding: '8px' }}>{fmt(d.portfolio)}원</td>
                              <td style={{ padding: '8px', color: last ? '#059669' : 'inherit' }}>
                                {Math.round(d.monthlyDiv)}만원
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="chart-note" style={{ marginTop: 8 }}>
                    💡 {startAge}세 {fmt(rows[0].portfolio)}원 → {targetAge}세 {fmt(rows[rows.length-1].portfolio)}원,
                    월배당 {Math.round(rows[rows.length-1].monthlyDiv)}만원으로 목표({result.monthly_target}만원) 도달.
                  </div>
                  <div style={{ marginTop: 8, fontSize: 11.5, color: 'var(--text-sub)',
                       background: 'var(--surface2)', borderRadius: 8, padding: '8px 10px' }}>
                    ⚙️ 가정 — 세후 배당률 {afterTaxYield ? afterTaxYield.toFixed(1) : '-'}%
                    · 배당 전액 재투자(복리)
                    · 적립금 연 {result.invest_growth || 0}% 증액
                    · 주가성장 제외(보수적)
                  </div>
                </div>
              )
            })()}

            {/* ★ 목표 달성 가속기 — "행동을 바꾸면 몇 년 빨라지나" (항상 표시) */}
            {(growthScenarios?.some(x => x.age) || investScenarios?.some(x => x.age)) && (() => {
              const baseAge = investScenarios?.find(x => x.extra === 0)?.age || null
              return (
                <div className="card" style={{ borderLeft: '3px solid #7c3aed' }}>
                  <h3 className="card-title">🚀 목표 달성 가속기
                    <span className="title-sub">행동을 바꾸면 몇 년 빨라지나</span>
                  </h3>

                  {/* 투자금 증가 시나리오 */}
                  {investScenarios?.some(x => x.age) && (
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--border)', marginBottom: 8 }}>
                        💰 월 투자금 증액 → 달성 나이 단축
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {investScenarios.map(({ extra, monthlyInvest, age }) => {
                          const gain = baseAge && age ? baseAge - age : 0
                          const isBase = extra === 0
                          const barWidth = age ? Math.max(20, 100 - (age - (result.age || 25)) * 1.5) : 5
                          return (
                            <div key={extra} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                              <div style={{ width: 120, fontSize: 12, fontWeight: isBase ? 600 : 400,
                                   color: isBase ? 'var(--text)' : 'var(--text-sub)', flexShrink: 0 }}>
                                월 {monthlyInvest}만원{extra > 0 ? ` (+${extra}만)` : ' (현재)'}
                              </div>
                              <div style={{ flex: 1, height: 24, background: 'var(--surface2)', borderRadius: 6, overflow: 'hidden' }}>
                                <div style={{ width: `${barWidth}%`, height: '100%',
                                     background: isBase ? 'var(--text-sub)' : gain > 0 ? '#7c3aed' : '#2563eb',
                                     borderRadius: 6, display: 'flex', alignItems: 'center', paddingLeft: 8 }}>
                                  <span style={{ fontSize: 11, fontWeight: 700, color: '#fff', whiteSpace: 'nowrap' }}>
                                    {age ? `${age}세 달성` : '미달성'}
                                  </span>
                                </div>
                              </div>
                              {gain > 0 && (
                                <div style={{ width: 70, fontSize: 12, fontWeight: 700, color: '#7c3aed', textAlign: 'right', flexShrink: 0 }}>
                                  ⚡ {gain}년 단축
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* 소득 상승(적립 증가) 시나리오 */}
                  {growthScenarios?.some(x => x.age) && (
                    <div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--border)', marginBottom: 8 }}>
                        📈 연봉 상승(적립 연 증가) → 달성 나이 단축
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}>
                        {growthScenarios.map(({ gr, age }) => {
                          const active = Number(result.invest_growth) === gr
                          const base0 = growthScenarios.find(x => x.gr === 0)?.age
                          const gain = base0 && age ? base0 - age : 0
                          return (
                            <div key={gr} style={{ textAlign: 'center', padding: '10px 4px', borderRadius: 10,
                                 background: active ? 'rgba(37,99,235,.10)' : 'var(--surface2)',
                                 border: `1px solid ${active ? 'var(--blue)' : 'var(--border)'}` }}>
                              <div style={{ fontSize: 11, color: 'var(--text-sub)', marginBottom: 2 }}>
                                {gr === 0 ? '고정 (현재)' : `+${gr}%/년`}
                              </div>
                              <div style={{ fontSize: 20, fontWeight: 800, color: active ? 'var(--blue)' : 'var(--text)' }}>
                                {age ? `${age}세` : '미달성'}
                              </div>
                              {gr > 0 && gain > 0 && (
                                <div style={{ fontSize: 11, color: '#059669', fontWeight: 700 }}>⚡ {gain}년 단축</div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                  <div className="chart-note" style={{ marginTop: 10 }}>
                    💡 수익률보다 투자금 증가가 달성 시점에 더 직접적인 영향을 미칩니다. 승진·연봉 인상 시 투자금을 우선 늘리세요.
                  </div>
                </div>
              )
            })()}

            {/* ★ AI 모델 정보 카드 (항상 표시 — 발표 방어용) */}
            <div className="card" style={{ borderLeft: '3px solid #1456f0' }}>
              <h3 className="card-title">🤖 AI 모델 정보
                <span className="title-sub">실제 머신러닝 기반 배당 삭감 예측 시스템</span>
              </h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
                <div style={{ padding: '12px 14px', background: 'rgba(20,86,240,.05)', borderRadius: 10,
                     border: '1px solid rgba(20,86,240,.15)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#1456f0', marginBottom: 8, letterSpacing: 0.5 }}>
                    📚 학습 데이터
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.8 }}>
                    <div>🏢 <b>210</b>개 국내 배당주</div>
                    <div>📊 <b>1,679</b>개 관측치</div>
                    <div>📅 <b>2013~2025</b></div>
                    <div>📂 출처: DART 재무 데이터</div>
                  </div>
                </div>
                <div style={{ padding: '12px 14px', background: 'rgba(5,150,105,.05)', borderRadius: 10,
                     border: '1px solid rgba(5,150,105,.15)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#059669', marginBottom: 8, letterSpacing: 0.5 }}>
                    🧠 모델 구조
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text)', lineHeight: 1.9 }}>
                    <div>⚙️ <b>Survival 리스크 모델</b></div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted,#cbd5e1)', marginBottom: 4 }}>
                      배당 삭감까지 걸리는 시간을 확률로 예측하는<br/>
                      생존분석 기반 배당 지속성 판별 모델.<br/>
                      FCF·배당성향·이자보상배율 등 재무지표로<br/>
                      학습하며, DART 공시 데이터를 사용합니다.
                    </div>
                    <div>🟢 INTACT — 삭감 위험 낮음</div>
                    <div>🟡 WEAKENING — 위험 신호 감지</div>
                    <div>🔴 BROKEN — 삭감 발생 또는 임박</div>
                  </div>
                </div>
                <div style={{ padding: '12px 14px', background: 'rgba(124,58,237,.05)', borderRadius: 10,
                     border: '1px solid rgba(124,58,237,.15)' }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: '#7c3aed', marginBottom: 8, letterSpacing: 0.5 }}>
                    ✅ 검증 결과
                  </div>
                  <div style={{ fontSize: 13, color: 'var(--text)', lineHeight: 1.8 }}>
                    <div>🔁 <b>GroupKFold</b></div>
                    <div>📈 PR-AUC <b>0.801</b></div>
                    <div>🎯 상위 20% 정밀도</div>
                    <div style={{ fontWeight: 700, color: '#7c3aed' }}>    <b>0.96</b></div>
                  </div>
                </div>
              </div>
              <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-sub)',
                   background: 'var(--surface2)', borderRadius: 8, padding: '8px 12px' }}>
                💡 10개 재무 피처(FCF·배당커버리지·영업현금흐름 등)를 입력받아 배당 삭감 위험을 3단계로 분류합니다.
                SHAP(Explainable AI)으로 각 지표의 기여도를 정량화하여 "왜 위험한가"를 설명합니다.
              </div>
            </div>

            {/* ★ 투자 성향 정보 (항상 표시) */}
            {(() => {
              const riskKey = result.input?.risk_tolerance || form.risk_tolerance || 'moderate'
              const selectedRisk = RISK_OPTIONS.find(r => r.value === riskKey) || RISK_OPTIONS[1]
              const riskColor = { conservative: '#059669', moderate: '#2563eb', aggressive: '#dc2626' }[riskKey] || '#2563eb'
              return (<>
                <div className="card" style={{ borderLeft: `3px solid ${riskColor}` }}>
                  <h3 className="card-title">📊 선택된 투자 성향
                    <span className="title-sub">포트폴리오 구성 기준</span>
                  </h3>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8, marginBottom: 12 }}>
                    {RISK_OPTIONS.map(opt => {
                      const active = opt.value === riskKey
                      const col = { conservative: '#059669', moderate: '#2563eb', aggressive: '#dc2626' }[opt.value]
                      return (
                        <div key={opt.value} style={{
                          padding: '12px 10px', borderRadius: 10, textAlign: 'center',
                          background: active ? `${col}12` : 'var(--surface2)',
                          border: `2px solid ${active ? col : 'var(--border)'}`,
                          opacity: active ? 1 : 0.6,
                        }}>
                          <div style={{ fontSize: 13, fontWeight: 700, color: active ? col : 'var(--text-sub)', marginBottom: 4 }}>
                            {opt.label} {active && '✓'}
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--text-sub)', lineHeight: 1.5 }}>
                            <div>수익률 <b style={{ color: col }}>{opt.returnRange}</b></div>
                            <div>MDD <b style={{ color: opt.value === 'aggressive' ? '#dc2626' : 'var(--text-sub)' }}>{opt.mdd}</b></div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  <div style={{ padding: '12px 14px', background: `${riskColor}08`, borderRadius: 10,
                       border: `1px solid ${riskColor}25` }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                      <div>
                        <div style={{ fontSize: 11, color: 'var(--text-sub)', marginBottom: 3 }}>📈 기대 수익률</div>
                        <div style={{ fontSize: 16, fontWeight: 700, color: riskColor }}>{selectedRisk.returnRange}</div>
                      </div>
                      <div>
                        <div style={{ fontSize: 11, color: 'var(--text-sub)', marginBottom: 3 }}>📉 예상 최대 낙폭(MDD)</div>
                        <div style={{ fontSize: 16, fontWeight: 700, color: '#dc2626' }}>{selectedRisk.mdd}</div>
                      </div>
                      <div style={{ gridColumn: '1 / -1' }}>
                        <div style={{ fontSize: 11, color: 'var(--text-sub)', marginBottom: 3 }}>🧩 구성 특징</div>
                        <div style={{ fontSize: 13, color: 'var(--text)' }}>{selectedRisk.composition}</div>
                      </div>
                      <div style={{ gridColumn: '1 / -1' }}>
                        <div style={{ fontSize: 11, color: 'var(--text-sub)', marginBottom: 3 }}>👤 추천 대상</div>
                        <div style={{ fontSize: 13, color: 'var(--text)', fontWeight: 600 }}>{selectedRisk.target}</div>
                      </div>
                    </div>
                  </div>
                </div>
              {/* 추천 기준 패널 — ARCHETYPE_RATIONALE */}
              <RationalePanel
                rationale={result.archetype?.rationale}
                label={result.archetype?.label}
              />
              </>)
            })()}

            {/* ② 추천 포트폴리오 — "그래서 뭘 사야 하나" */}
            {result.recommendations?.length > 0 && (() => {
              const recs = [...result.recommendations].sort((a, b) => b.weight_pct - a.weight_pct)
              const monthly = recs.reduce((s, r) => s + (r.est_monthly_div_after_tax || 0), 0)
              const tgtYield    = result.target_yield
              const rawYield    = result.raw_target_yield   // 클램프 이전 순수 역산값
              const yieldCapped = result.yield_capped       // true면 20% 상한 적용됨
              return (
                <div className="card">
                  <h3 className="card-title">🧩 추천 포트폴리오
                    <span className="title-sub">핵심 종목 + 분산 자산 총 {recs.length}개 · 세후 월배당 약 {monthly.toFixed(1)}만원</span>
                  </h3>
                  {tgtYield > 0 && (
                    <div style={{ marginBottom: 12, padding: '8px 12px',
                      background: yieldCapped ? 'rgba(245,158,11,.07)' : 'rgba(5,150,105,.06)',
                      borderRadius: 8,
                      border: `1px solid ${yieldCapped ? 'rgba(245,158,11,.25)' : 'rgba(5,150,105,.15)'}`,
                      fontSize: 12.5 }}>
                      {yieldCapped ? (
                        /* 20% 상한 적용 시 — 명확한 설명 표시 */
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                          <span style={{ fontWeight: 700, color: '#d97706' }}>📐 필요 수익률</span>
                          <span style={{ fontWeight: 800, fontSize: 15, color: '#d97706', textDecoration: 'line-through', opacity: .7 }}>
                            {rawYield ? `${Number(rawYield).toFixed(1)}%` : '—'}
                          </span>
                          <span style={{ color: '#d97706', fontWeight: 600 }}>→ 엔진 상한 20% 적용</span>
                          <span style={{ color: 'var(--text-sub)', fontSize: 11.5 }}>
                            현재 자산({result.input?.investable?.toLocaleString()}만원)으로 목표({result.input?.monthly_target}만원/월)를
                            즉시 달성하려면 비현실적 수익률이 필요 — 적립 복리로 장기 달성 계획 수립
                          </span>
                        </div>
                      ) : (
                        /* 정상 범위 — 기존 표시 */
                        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                          <span style={{ fontWeight: 700, color: '#059669' }}>🎯 역산 목표수익률</span>
                          <span style={{ fontWeight: 800, fontSize: 15, color: '#059669' }}>{Number(tgtYield).toFixed(2)}%</span>
                          <span style={{ color: 'var(--text-sub)' }}>월 {result.input?.monthly_target}만원 목표 ÷ 투자금 {result.input?.investable?.toLocaleString()}만원으로 산출</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* AI 선별 기준 설명 */}
                  <div style={{ marginBottom: 14, padding: '12px 14px', background: 'rgba(20,86,240,.04)',
                       borderRadius: 10, border: '1px solid rgba(20,86,240,.12)' }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: '#1456f0', marginBottom: 8 }}>
                      🔍 AI가 이 종목들을 선택한 방식
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8, fontSize: 12 }}>
                      {[
                        { icon: '✂️', title: '배당 삭감 위험', desc: 'Survival 모델로 재무 지표를 분석해 삭감 위험이 낮은 종목 우선 선별' },
                        { icon: '📈', title: 'Total Return', desc: '배당수익률만이 아닌 자본차익까지 포함한 총수익률 기준으로 평가' },
                        { icon: '🌐', title: '자산군 분산', desc: '한국·미국·리츠·방어형 4축으로 분산해 특정 시장 충격 최소화' },
                        { icon: '🎯', title: '역할 중복 제거', desc: 'SCHD·VIG·DGRO처럼 역할이 겹치는 ETF는 대표 1개로 정리해 비중 왜곡 방지' },
                      ].map(item => (
                        <div key={item.title} style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                          <span style={{ fontSize: 14, flexShrink: 0 }}>{item.icon}</span>
                          <div>
                            <div style={{ fontWeight: 700, color: 'var(--text)', marginBottom: 2 }}>{item.title}</div>
                            <div style={{ color: 'var(--text-sub)', lineHeight: 1.5 }}>{item.desc}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div style={{ marginTop: 10, fontSize: 11.5, color: 'var(--text-sub)', lineHeight: 1.5 }}>
                      AI는 위험 분산을 위해 내부적으로 <b style={{ color: '#1456f0' }}>{recs.length}개 자산</b>으로 포트폴리오를 구성합니다.
                      실제 매수해야 할 <b style={{ color: '#1456f0' }}>핵심 종목은 아래 상위 5~8개</b>이며, 나머지는 충격 분산용 소액 비중입니다.
                    </div>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {(showAllHoldings ? recs : recs.slice(0, 6)).map((r, i) => {
                      const role = holdingRole(r)
                      const desc = getStockDescription(r)
                      // composite_risk_score 색상
                      const crs = r.composite_risk_score
                      const gate = r.risk_gate || (crs >= 75 ? 'BLOCK' : crs >= 50 ? 'WARN' : 'PASS')
                      const gateColor = gate === 'BLOCK' ? '#dc2626' : gate === 'WARN' ? '#d97706' : '#059669'
                      const gateLabel = gate === 'BLOCK' ? '위험' : gate === 'WARN' ? '주의' : '안전'
                      // ml_status 배지
                      const mlStatus = r.ml_status
                      const mlColor = mlStatus === 'BROKEN' ? '#dc2626' : mlStatus === 'WEAKENING' ? '#d97706' : '#059669'
                      const mlLabel = mlStatus === 'BROKEN' ? 'BROKEN' : mlStatus === 'WEAKENING' ? 'WEAK' : 'INTACT'
                      return (
                      <div key={i} style={{ padding: '10px 12px', background: 'var(--surface2)',
                           borderRadius: 10, border: `1px solid ${gate === 'BLOCK' ? '#fca5a5' : 'var(--border)'}` }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
                          <span style={{ width: 8, height: 8, borderRadius: 99, background: ASSET_COLOR[r.asset_class] || '#2563eb', flexShrink: 0 }} />
                          <span style={{ flex: 1, minWidth: 0, fontSize: 13, fontWeight: 700,
                                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.name}</span>
                          <span style={{ fontSize: 10.5, fontWeight: 700, padding: '2px 7px', borderRadius: 5,
                                background: `${role.c}1a`, color: role.c, flexShrink: 0 }}>{role.t}</span>
                          <div style={{ width: 60, height: 7, background: 'var(--border)', borderRadius: 4, overflow: 'hidden', flexShrink: 0 }}>
                            <div style={{ width: `${Math.min(100, r.weight_pct * 6)}%`, height: '100%', background: ASSET_COLOR[r.asset_class] || '#2563eb' }} />
                          </div>
                          <span style={{ width: 42, textAlign: 'right', fontSize: 13, fontWeight: 700, flexShrink: 0 }}>{r.weight_pct}%</span>
                        </div>
                        {/* Risk Engine 출력: composite_risk_score / ml_status / fit_score */}
                        <div style={{ display: 'flex', gap: 6, alignItems: 'center', paddingLeft: 18, marginBottom: desc ? 4 : 0, flexWrap: 'wrap' }}>
                          {crs != null && (
                            <span style={{ fontSize: 10.5, padding: '1px 6px', borderRadius: 4,
                              background: `${gateColor}18`, color: gateColor, fontWeight: 700 }}>
                              위험 {Math.round(crs)} · {gateLabel}
                            </span>
                          )}
                          {mlStatus === 'NO_DATA' ? (
                            <span style={{ fontSize: 10.5, padding: '1px 6px', borderRadius: 4,
                              background: '#f1f5f9', color: '#64748b', fontWeight: 600,
                              border: '1px dashed #cbd5e1' }}>
                              데이터부족
                            </span>
                          ) : mlStatus && (
                            <span style={{ fontSize: 10.5, padding: '1px 6px', borderRadius: 4,
                              background: `${mlColor}12`, color: mlColor, fontWeight: 600 }}>
                              ML:{mlLabel}
                            </span>
                          )}
                          {r.fit_score != null && (
                            <span style={{ fontSize: 10.5, padding: '1px 6px', borderRadius: 4,
                              background: 'rgba(20,86,240,.08)', color: '#1456f0', fontWeight: 600 }}>
                              적합도 {Number(r.fit_score).toFixed(0)}점
                            </span>
                          )}
                          {/* 적합도 세부: yield_fit / risk_fit / age_fit (0-100 스케일) */}
                          {r.yield_fit != null && (
                            <span style={{ fontSize: 10, color: 'var(--text-sub)', display: 'flex', gap: 4 }}>
                              {[
                                { label: '수익률', v: r.yield_fit },
                                { label: '위험', v: r.risk_fit },
                                { label: '나이', v: r.age_fit },
                              ].map(({ label, v }) => (v != null && v > 2) && (
                                <span key={label} style={{ padding: '0 4px', borderRadius: 3,
                                  background: v >= 70 ? '#d1fae5' : v >= 40 ? '#fef3c7' : '#fee2e2',
                                  color: v >= 70 ? '#065f46' : v >= 40 ? '#92400e' : '#991b1b',
                                  fontWeight: 500 }}>
                                  {label} {Math.round(v)}
                                </span>
                              ))}
                            </span>
                          )}
                          {r.expected_yield != null && (
                            <span style={{ fontSize: 10.5, color: 'var(--text-sub)' }}>
                              배당 {Number(r.expected_yield).toFixed(1)}%
                            </span>
                          )}
                        </div>
                        {/* 추천 이유 (AI 개인화 설명) */}
                        {r.recommendation_reason && (
                          <div style={{ fontSize: 11, color: '#1456f0', lineHeight: 1.5, paddingLeft: 18,
                            marginBottom: 2, opacity: 0.85 }}>
                            💡 {r.recommendation_reason}
                          </div>
                        )}
                        {/* 종목 설명 (자산 정보) */}
                        {desc && (
                          <div style={{ fontSize: 11.5, color: 'var(--text-sub)', lineHeight: 1.55, paddingLeft: 18 }}>
                            {desc}
                          </div>
                        )}
                      </div>
                      )
                    })}
                  </div>
                  {recs.length > 5 && (
                    <button type="button" onClick={() => setShowAllHoldings(v => !v)}
                      style={{ marginTop: 8, width: '100%', padding: '6px', fontSize: 12, fontWeight: 600,
                        borderRadius: 8, cursor: 'pointer', color: 'var(--blue)',
                        background: 'transparent', border: '1px solid var(--border)' }}>
                      {showAllHoldings ? '▲ 접기' : `▼ +${recs.length - 5}개 더 보기`}
                    </button>
                  )}
                </div>
              )
            })()}

            {/* ②-b 오늘의 액션 — "투자 코치" */}
            {(() => {
              const actions = []
              const ra = result.risk_alerts || []
              if (ra.length > 0) {
                actions.push({ icon: '⚠️', text: `${ra[0].name} 배당 위험 신호 — 비중 점검 또는 대체 검토` })
              }
              const rc = result.survival?.risk_contribution || []
              const wmap = Object.fromEntries((result.survival?.concentration_groups || []))
              const over = rc.map(([g, p]) => ({ g, p, w: wmap[g] || 0 }))
                .filter(x => x.w > 0 && x.p >= x.w * 1.4).sort((a, b) => b.p - a.p)[0]
              if (over) {
                const ko = GROUP_RISK_REASON[over.g]?.ko || over.g
                actions.push({ icon: '📉', text: `「${ko}」 비중 축소로 분산 강화 (위험 ${over.p}% vs 비중 ${over.w}%)` })
              }
              if (result.isa_strategy) {
                actions.push({ icon: '🏦', text: `ISA 비과세 한도 ${result.isa_strategy.tax_free_limit}만원 활용 — 국내상장ETF·리츠 우선 편입` })
              }
              const hasSchd = (result.recommendations || []).some(r => r.ticker === 'SCHD')
              if (!hasSchd) actions.push({ icon: '🌱', text: 'SCHD·VIG 등 배당성장 ETF 편입으로 장기 복리 강화' })
              const top = actions.slice(0, 3)
              if (top.length === 0) return null
              return (
                <div className="card" style={{ borderLeft: '3px solid #d97706' }}>
                  <h3 className="card-title" style={{ fontSize: 15 }}>🎬 오늘의 액션
                    <span className="title-sub">지금 바로 할 수 있는 것</span>
                  </h3>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {top.map((a, i) => (
                      <div key={i} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', fontSize: 13.5 }}>
                        <span style={{ fontWeight: 800, color: '#d97706' }}>{i + 1}</span>
                        <span>{a.icon} {a.text}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )
            })()}

            {/* ②-c 내 현금흐름 여정 타임라인 */}
            {compoundData?.length > 1 && (() => {
              const startAge = compoundData[0].age
              const achAge = achieveAge ? Math.ceil(achieveAge) : (mc?.p50Age ? Math.ceil(mc.p50Age) : null)
              const tgt = Number(result.monthly_target)
              const leanAge = (fireTargets || []).find(t => t.name === 'Lean FIRE')?.age
              const regAge  = (fireTargets || []).find(t => t.name === '일반 FIRE')?.age
              // 마일스톤 노드 구성 (나이순)
              const nodes = []
              nodes.push({ age: startAge, label: '🌱 시작', sub: `월배당 ${Math.round(compoundData[0].monthlyDiv)}만` })
              const midAges = [Math.round((startAge + (achAge || startAge + 20)) / 2)]
              midAges.forEach(a => {
                const d = compoundData.reduce((b, x) => Math.abs(x.age - a) < Math.abs(b.age - a) ? x : b, compoundData[0])
                nodes.push({ age: d.age, label: `월배당 ${Math.round(d.monthlyDiv)}만` })
              })
              if (achAge) nodes.push({ age: achAge, label: `🎯 목표 ${tgt}만 달성`, hl: true })
              if (leanAge && leanAge !== achAge) nodes.push({ age: leanAge, label: '🏠 Lean FIRE' })
              if (regAge && regAge !== achAge) nodes.push({ age: regAge, label: '🌴 일반 FIRE' })
              nodes.sort((a, b) => a.age - b.age)
              return (
                <div className="card">
                  <h3 className="card-title" style={{ fontSize: 15 }}>🗺️ 내 현금흐름 여정
                    <span className="title-sub">{startAge}세부터 FIRE까지</span>
                  </h3>
                  <div style={{ display: 'flex', overflowX: 'auto', gap: 0, paddingBottom: 4 }}>
                    {nodes.map((n, i) => (
                      <div key={i} style={{ flex: '1 0 auto', minWidth: 90, textAlign: 'center', position: 'relative' }}>
                        {i < nodes.length - 1 && (
                          <div style={{ position: 'absolute', top: 17, left: '50%', width: '100%', height: 2,
                               background: 'var(--border)' }} />
                        )}
                        <div style={{ position: 'relative', width: 14, height: 14, borderRadius: 99, margin: '10px auto 0',
                             background: n.hl ? '#2563eb' : 'var(--surface)', border: `2px solid ${n.hl ? '#2563eb' : 'var(--border)'}`, zIndex: 1 }} />
                        <div style={{ fontSize: 13, fontWeight: 800, marginTop: 6, color: n.hl ? '#2563eb' : 'var(--text)' }}>{n.age}세</div>
                        <div style={{ fontSize: 11, color: 'var(--text-sub)', lineHeight: 1.3 }}>{n.label}</div>
                        {n.sub && <div style={{ fontSize: 10, color: 'var(--text-sub)', opacity: .7 }}>{n.sub}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })()}

            {/* ③ 상세 분석 접기/펼치기 */}
            <button type="button" onClick={() => setShowAnalysis(v => !v)} className="card"
              style={{ width: '100%', textAlign: 'center', cursor: 'pointer', fontWeight: 700, fontSize: 14,
                       color: 'var(--blue)', border: '1px dashed var(--blue)', background: 'transparent' }}>
              {showAnalysis ? '▲ 상세 분석 접기' : '▼ 상세 분석 보기 (건강도·생존확률·FIRE·백테스트 등)'}
            </button>

            {showAnalysis && (<>

            {/* 데이터 기준일 / 출처 배너 */}
            {result.data_freshness && (
              <DataFreshnessPanel freshness={result.data_freshness} />
            )}

            {/* ★ 단일 헤드라인: AI 현금흐름 건강도 */}
            {result.survival?.health_score != null && (() => {
              const sv = result.survival
              const sm = sv.sub_metrics || {}
              // 달성률 = '적립 포함' 목표 도달 확률(Monte Carlo) 우선. 백엔드 sub_metrics는
              // '현 보유분 배당만' 기준이라 적립형(청년)에서 0%로 나와 오해 유발.
              const ach = (mc && mc.achieveProb != null) ? mc.achieveProb : (sm.achievement ?? 0)
              const inflScore = sm.inflation_score ?? 50
              const concQ = Math.max(0, Math.min(100, (1 - (sv.concentration_hhi || 0)) * 100))
              const hs = Math.round(Math.max(0, Math.min(95,
                0.40 * (sm.survival ?? 0) + 0.25 * ach + 0.20 * inflScore + 0.15 * concQ)))
              const grade = hs >= 85 ? 'A+' : hs >= 75 ? 'A' : hs >= 62 ? 'B' : hs >= 50 ? 'C' : 'D'
              const gColor = hs >= 75 ? '#059669' : hs >= 62 ? '#2563eb' : hs >= 50 ? '#d97706' : '#dc2626'
              const lvColor = (lv) => lv === '높음' || lv === '약' ? '#dc2626' : lv === '중간' || lv === '보통' ? '#d97706' : '#059669'
              const Metric = ({ label, value, color }) => (
                <div style={{ flex: 1, minWidth: 120, textAlign: 'center', padding: '8px 6px' }}>
                  <div style={{ fontSize: 11, color: 'var(--text-sub)' }}>{label}</div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: color || 'var(--text)', marginTop: 2 }}>{value}</div>
                </div>
              )
              return (
                <div className="card" style={{ display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap',
                     borderTop: `3px solid ${gColor}` }}>
                  <div style={{ textAlign: 'center', minWidth: 150 }}>
                    <div style={{ fontSize: 12, color: 'var(--text-sub)', fontWeight: 600 }}>AI 현금흐름 건강도
                      <div style={{ fontSize: 9.5, fontWeight: 400, color: 'var(--text-muted, #94a3b8)', marginTop: 2 }}>
                        AI Cashflow OS 내부 산정 지표 · 공인 금융기관 평가 아님
                      </div>
                    </div>
                    <div style={{ fontSize: 56, fontWeight: 800, color: gColor, lineHeight: 1.05 }}>
                      {hs}<span style={{ fontSize: 22, color: 'var(--text-sub)' }}>/100</span>
                    </div>
                    <div style={{ display: 'inline-block', marginTop: 4, padding: '2px 14px', borderRadius: 999,
                         background: gColor, color: '#fff', fontWeight: 800, fontSize: 16 }}>{grade}</div>
                  </div>
                  <div style={{ flex: 1, minWidth: 280, display: 'flex', flexWrap: 'wrap',
                       borderLeft: '1px solid var(--border)' }}>
                    <Metric label="🛡️ 현재 소득 유지확률" value={`${sm.survival}%`}
                            color={sm.survival >= 70 ? '#059669' : sm.survival >= 40 ? '#d97706' : '#dc2626'} />
                    <Metric label="🎯 목표 소득 달성확률" value={`${Math.round(ach)}%`}
                            color={ach >= 70 ? '#059669' : ach >= 40 ? '#d97706' : '#dc2626'} />
                    <Metric label="✂️ 배당컷 위험" value={sm.cut_risk_level} color={lvColor(sm.cut_risk_level)} />
                    <Metric label="🔥 인플레 방어" value={sm.inflation_level} color={lvColor(sm.inflation_level)} />
                  </div>
                </div>
              )
            })()}

            {/* HERO (보조 지표) */}
            <div id="sec-hero" className="hero-card">
              <div className="hero-grid">

                {/* ① 목표 달성 시점 (Monte Carlo 시나리오) */}
                <div className="hero-item main">
                  <div className="hero-label">🗓️ 목표 달성 시점</div>
                  {mc ? (
                    <>
                      <div className="hero-value highlight">
                        <span className="hv-num">{achieveAge ? Math.ceil(achieveAge) : (mc.p50Age ? Math.ceil(mc.p50Age) : '—')}</span>
                        <span className="hv-unit">세</span>
                      </div>
                      <div className="hero-sub">목표 달성 예상 나이 · 비관~낙관은 Monte Carlo 범위</div>
                      {/* 시나리오 범위 */}
                      <div className="scenario-row">
                        <span className="sc-item pessimistic">
                          비관 {mc.p90Age ? `${Math.ceil(mc.p90Age)}세` : '미달성'}
                        </span>
                        <span className="sc-sep">·</span>
                        <span className="sc-item base">
                          중간 {achieveAge ? `${Math.ceil(achieveAge)}세` : '미달성'}
                        </span>
                        <span className="sc-sep">·</span>
                        <span className="sc-item optimistic">
                          낙관 {mc.p10Age ? `${Math.ceil(mc.p10Age)}세` : '미달성'}
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
                      fontSize: 12, color: 'var(--text-sub)', lineHeight: 1.6,
                    }}>
                      <div style={{ color: 'var(--border)', fontWeight: 600, marginBottom: 4 }}>
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
                      style={{ borderLeft: `3px solid ${ASSET_COLOR[ax.asset_class] || '#2563eb'}` }}>
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
                <span className="title-sub">매달 {result.monthly_invest}만원
                  {(result.invest_growth > 0) && ` (연 ${result.invest_growth}% 증액)`}
                  {' '}× 배당 재투자 · 세후 기준</span>
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
                  <ReferenceLine y={result.monthly_target} stroke="#d97706" strokeDasharray="4 4"
                    label={{ value: `목표 ${result.monthly_target}만원`, fill: '#d97706', fontSize: 11, position: 'right' }} />

                  {/* 중간 달성 시점 */}
                  {(achieveAge || mc?.p50Age) && (
                    <ReferenceLine x={Math.ceil(achieveAge || mc.p50Age)} stroke="#059669" strokeDasharray="4 4"
                      label={{ value: `🎯 ${Math.ceil(achieveAge || mc.p50Age)}세`, fill: '#059669', fontSize: 11, position: 'top' }} />
                  )}

                  <Line type="monotone" dataKey="high" stroke="rgba(52,211,153,0.4)"
                    strokeWidth={1} dot={false} name="낙관" />
                  <Line type="monotone" dataKey="base" stroke="#059669"
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
              {(() => {
                const amts = cashflowData.map(d => d.amount)
                const maxAmt = Math.max(...amts) || 1
                const median = [...amts].sort((a, b) => a - b)[Math.floor(amts.length / 2)] || 0
                return (
                  <div className="cashflow-grid">
                    {cashflowData.map(({ month, label, amount }) => {
                      const lump = amount > 0 && median > 0 && amount >= median * 2.5  // 연배당 집중월
                      return (
                        <div key={month} className={`cf-month ${amount > 0 ? 'has-div' : 'no-div'}`}>
                          <div className="cf-label">{label}</div>
                          <div className="cf-bar-wrap">
                            <div className="cf-bar"
                              style={{
                                height: `${Math.min(amount / maxAmt * 80, 80)}px`,
                                background: lump ? 'var(--blue, #2563eb)' : amount > 0 ? 'var(--green, #059669)' : 'var(--border)',
                                opacity: amount > 0 ? 1 : 0.3,
                              }}
                            />
                          </div>
                          <div className={`cf-amount ${amount > 0 ? 'green' : 'muted'}`}>
                            {amount > 0 ? `${amount}만` : '—'}
                          </div>
                          {lump && (
                            <div style={{ fontSize: 9, color: 'var(--blue)', fontWeight: 700, marginTop: 2 }}>
                              연 1회 집중
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )
              })()}
              <div className="chart-note">
                💡 파랑 막대(연 1회 집중)는 한국 배당주가 연 1회(주로 4월) 일괄 지급되어 그달에 몰린 것입니다 — 오류 아님.
                JEPI·O 등 월배당 ETF를 늘리면 매월 고르게 분산됩니다.
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
                        <span className="rc-dot" style={{ background: ASSET_COLOR[r.asset_class] || '#2563eb' }} />
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
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6 }}>
                        {selectionReasons(r).map((rs, j) => (
                          <span key={j} style={{
                            fontSize: 10.5, fontWeight: 600, borderRadius: 5, padding: '2px 7px',
                            background: rs.ok ? 'rgba(5,150,105,.12)' : 'rgba(217,119,6,.12)',
                            color: rs.ok ? '#059669' : '#d97706',
                          }}>
                            {rs.ok ? '✓' : '⚠'} {rs.text}
                          </span>
                        ))}
                      </div>
                      <div className="rc-reason" style={{ fontSize: 11, opacity: .75, marginTop: 5 }}>{r.description}</div>
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
                        <StockRationaleCard rec={r} />
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

            {/* SHAP 배당 삭감 예측 근거 (XAI) */}
            <ShapExplainPanel recs={result.recommendations} />

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

            {/* FIRE 통합 카드 — 배당목표 / Lean / 일반 FIRE 한눈에 (헤드라인과 동일 엔진) */}
            {fireTargets?.length > 0 && (
                <div className="card" id="sec-fire" style={{ scrollMarginTop: 16 }}>
                  <h3 className="card-title">🔥 FIRE 달성 한눈에
                    <span className="title-sub">
                      목표별 달성 나이
                      {result.invest_growth > 0 ? ` · 적립 연 ${result.invest_growth}% 증액 반영` : ' · 적립 고정'}
                    </span>
                  </h3>
                  <div style={{ display: 'grid', gridTemplateColumns: `repeat(${fireTargets.length}, 1fr)`, gap: 10 }}>
                    {fireTargets.map(({ icon, name, target, age }) => {
                      const ok = age != null
                      const color = !ok ? '#dc2626' : age <= 50 ? '#059669' : '#2563eb'
                      return (
                        <div key={name} style={{ textAlign: 'center', padding: '12px 8px',
                             border: '1px solid var(--border)', borderRadius: 12,
                             background: ok ? 'var(--surface2)' : 'rgba(220,38,38,.05)' }}>
                          <div style={{ fontSize: 12, color: 'var(--text-sub)' }}>{icon} {name}</div>
                          <div style={{ fontSize: 12, color: 'var(--text-sub)', marginTop: 2 }}>월 {target}만원</div>
                          <div style={{ fontSize: 26, fontWeight: 800, marginTop: 4, color }}>
                            {ok ? `${age}세` : '미달성'}
                          </div>
                          <div style={{ fontSize: 11, marginTop: 2, color: 'var(--text-sub)' }}>
                            {ok ? `${age - Number(result.age)}년 후 달성` : '기간 내 미달성'}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                  <div className="chart-note" style={{ marginTop: 10 }}>
                    ⚙️ 가정: 월 {result.monthly_invest}만원 적립
                    {result.invest_growth > 0 ? ` (연 ${result.invest_growth}% 증액)` : ' (고정)'}
                    {' · '}배당 {result.summary?.avg_dividend_yield ? Number(result.summary.avg_dividend_yield).toFixed(1) : '-'}% 재투자 복리
                    {' · '}주가성장 제외(보수적). 가정이 바뀌면 달성 나이도 달라집니다.
                  </div>

                  {/* 가속기는 상단 섹션에서 표시됨 */}
                </div>
            )}

            {/* 목표 달성 근거 — 상단에 이미 표시됨 (상세 분석에서는 복리 성장 그래프로 대체) */}

            {/* 현금흐름 마일스톤 — "내 인생이 어떻게 변하나" */}
            <div id="sec-cashflow" style={{ scrollMarginTop: 16 }}>
              <CashflowMilestone
                summary={result.summary}
                fire_plan={result.fire_plan}
                fireEarliest={(fireTargets || []).filter(t => t.age).sort((a, b) => a.age - b.age)[0] || null}
              />
            </div>

            {/* Portfolio Health OS 레이더 차트 */}
            {result.portfolio_health && (
              <div id="sec-health" style={{ scrollMarginTop: 16 }}>
                <HealthRadarChart health={result.portfolio_health} />
                {/* 점수 산정 기준 패널 — SCORING_RATIONALE */}
                <div style={{ padding: '0 16px 12px' }}>
                  <ScoringRationale scoringRationale={result.portfolio_health?.scoring_rationale} />
                </div>
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

            {/* 포트폴리오 배당 유지 시뮬레이션 */}
            {result.survival?.survival_probability != null && (() => {
              const s = result.survival
              const score = s.income_sustainability_score ?? s.survival_probability
              const color = score >= 75 ? '#059669' : score >= 55 ? '#d97706' : '#dc2626'
              const weightMap = Object.fromEntries(s.concentration_groups || [])
              const cmp = s.compare
              const thrLabel = s.threshold_type === 'user_target'
                ? `사용자 목표 ${s.threshold_monthly_만원}만원`
                : `현재 배당의 80% (${s.threshold_monthly_만원}만원)`
              const mlNote = s.ml_driven && s.ml_effective_count === 0
                ? 'ML 위험 신호 미적용 — 기본 위험률 사용'
                : s.ml_driven && s.ml_effective_count > 0
                  ? `ML 위험 신호 유효 종목 ${s.ml_effective_count}개`
                  : null
              return (
                <div id="sec-survival" className="card" style={{ scrollMarginTop: 16 }}>
                  <h3 className="card-title">
                    🛡️ 소득 지속성 점수
                    <span className="title-sub">Monte Carlo 시뮬레이션·집중도 통합 — 20년 배당 유지 시뮬레이션 결과</span>
                  </h3>
                  <div style={{ display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap', padding: '8px 4px' }}>
                    <div style={{ textAlign: 'center', minWidth: 140 }}>
                      <div style={{ fontSize: 52, fontWeight: 800, color, lineHeight: 1.1 }}>{score}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted, #cbd5e1)', marginTop: 4 }}>소득 지속성 점수 / 100</div>
                    </div>
                    <div style={{ flex: 1, minWidth: 220, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                      <div><div style={{ fontSize: 11, color: 'var(--text-muted,#cbd5e1)' }}>20년 유지 비율 (시뮬레이션)</div>
                        <div style={{ fontSize: 18, fontWeight: 700 }}>{s.survival_probability}%</div></div>
                      <div><div style={{ fontSize: 11, color: 'var(--text-muted,#cbd5e1)' }}>만기 유지 비율 (시뮬레이션)</div>
                        <div style={{ fontSize: 18, fontWeight: 700 }}>{s.endpoint_probability}%</div></div>
                      <div><div style={{ fontSize: 11, color: 'var(--text-muted,#cbd5e1)' }}>유지 기준</div>
                        <div style={{ fontSize: 13, fontWeight: 700 }}>{thrLabel}</div></div>
                      <div><div style={{ fontSize: 11, color: 'var(--text-muted,#cbd5e1)' }}>비관 시 최악연도</div>
                        <div style={{ fontSize: 18, fontWeight: 700 }}>{s.p10_worst_monthly}만원</div></div>
                    </div>
                  </div>

                  {mlNote && (
                    <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted,#cbd5e1)',
                                  padding: '4px 8px', background: 'var(--surface-2,rgba(0,0,0,.08))',
                                  borderRadius: 4, display: 'inline-block' }}>
                      ℹ️ {mlNote}
                    </div>
                  )}

                  {s.risk_contribution?.length > 0 && (
                    <div style={{ marginTop: 14 }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted,#cbd5e1)', marginBottom: 6 }}>
                        위험 기여도 (비중이 아니라 실제 위험) — 비중과 다르면 숨은 집중
                      </div>
                      <div style={{ display: 'flex', height: 12, borderRadius: 6, overflow: 'hidden' }}>
                        {s.risk_contribution.map(([g, pct], i) => (
                          <div key={g} title={`${g} 위험 ${pct}%`} style={{
                            width: `${pct}%`,
                            background: ['#dc2626','#d97706','#2563eb','#059669','#a78bfa','var(--text-sub)'][i % 6],
                          }} />
                        ))}
                      </div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 6, fontSize: 11 }}>
                        {s.risk_contribution.slice(0, 5).map(([g, pct]) => (
                          <span key={g} style={{ color: 'var(--text-muted,#cbd5e1)' }}>
                            {(GROUP_RISK_REASON[g]?.ko) || g}: 위험 <b style={{ color: '#283143' }}>{pct}%</b>
                            <span style={{ opacity: .5 }}> (비중 {weightMap[g] ?? 0}%)</span>
                          </span>
                        ))}
                      </div>
                      {(() => {
                        const top = s.risk_contribution
                          .map(([g, pct]) => ({ g, pct, w: weightMap[g] || 0 }))
                          .filter(x => x.w > 0 && x.pct >= x.w * 1.3)
                          .sort((a, b) => b.pct - a.pct)[0]
                        if (!top) return null
                        const r = GROUP_RISK_REASON[top.g]
                        return (
                          <div style={{ fontSize: 11.5, color: 'var(--text-sub)', marginTop: 8,
                               background: 'var(--surface2)', borderRadius: 8, padding: '8px 10px' }}>
                            💡 <b>{r?.ko || top.g}</b>는 비중 {top.w}%지만 위험 기여 {top.pct}%
                            {` — ${r?.why || '분산 효과가 낮음'} (비중 대비 ${(top.pct / top.w).toFixed(1)}배)`}
                          </div>
                        )
                      })()}
                    </div>
                  )}

                  {cmp && (cmp.delta_survival >= 2 ? (
                    <div style={{ marginTop: 14, background: 'rgba(52,211,153,.08)',
                                  border: '1px solid rgba(52,211,153,.25)', borderRadius: 10, padding: '12px 14px' }}>
                      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                        <div style={{ fontSize: 13 }}>
                          현재 생존 <b>{cmp.current.survival}%</b>
                          <span style={{ opacity: .6 }}> → </span>
                          분산보정 시 <b style={{ color: '#059669' }}>{cmp.optimized.survival}%</b>
                        </div>
                        <div style={{ fontSize: 12, color: '#059669', fontWeight: 700 }}>+{cmp.delta_survival}%p</div>
                      </div>
                      {cmp.actions?.length > 0 && (
                        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                          {cmp.actions.map((a, i) => (
                            <span key={i} style={{
                              fontSize: 11, fontWeight: 600, borderRadius: 6, padding: '3px 8px',
                              background: a.type === 'trim' ? 'rgba(248,113,113,.15)' : 'rgba(52,211,153,.15)',
                              color: a.type === 'trim' ? '#dc2626' : '#059669',
                            }}>
                              {a.type === 'trim' ? '−' : '+'} {a.label} {a.pct_of_total}%p
                            </span>
                          ))}
                        </div>
                      )}
                      <div style={{ fontSize: 12, color: 'var(--text-muted,#475569)', marginTop: 8 }}>💡 {cmp.action_summary}</div>
                    </div>
                  ) : (
                    <div style={{ marginTop: 14, background: 'var(--surface2)', borderRadius: 10, padding: '10px 14px',
                                  fontSize: 12, color: 'var(--text-sub)' }}>
                      ✅ 분산 최적화 개선 여지 미미(+{cmp.delta_survival}%p) — 현재 구조가 이미 균형적입니다. 유지 권장.
                    </div>
                  ))}

                  <div className="chart-note" style={{ marginTop: 10 }}>💡 {s.summary}</div>
                </div>
              )
            })()}

            {/* 행동편향 진단 요약 */}
            {result.behavioral_finance?.bias_count > 0 && (
              <div style={{
                background: '#ffffff', borderRadius: 16, padding: '20px 24px',
                border: '1px solid #dfe3ea', marginTop: 0,
              }}>
                <div style={{ fontSize: 15, fontWeight: 700, color: '#283143', marginBottom: 12 }}>
                  행동편향 진단
                </div>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12,
                }}>
                  <div style={{ fontSize: 28 }}>
                    {result.behavioral_finance.investor_type?.split(' ')[0]}
                  </div>
                  <div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#283143' }}>
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
                    background: '#ffffff', borderRadius: 8,
                    borderLeft: `3px solid ${b.severity === 'high' ? '#ef4444' : b.severity === 'medium' ? '#d97706' : '#64748b'}`,
                    fontSize: 12, color: 'var(--text-sub)',
                  }}>
                    <span style={{ fontWeight: 600, color: '#283143' }}>{b.bias_name}</span>
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
                  background: '#ffffff', borderRadius: 16, padding: '20px 24px',
                  border: '1px solid #dfe3ea', marginTop: 0,
                }}>
                  <div style={{ fontSize: 15, fontWeight: 700, color: '#283143', marginBottom: 12 }}>
                    AI 분석 리포트
                  </div>
                  <div style={{
                    fontSize: 13, color: 'var(--text-sub)', lineHeight: 1.8,
                    whiteSpace: 'pre-line',
                  }}>
                    {text}
                  </div>
                </div>
              )
            })()}

            {/* ── AI Portfolio Advisor ── */}
            <div id="sec-advisor" style={{ scrollMarginTop: 16 }}>
              <AdvisorPanel portfolio={result} />
            </div>

            {/* ── FIRE 역산 시뮬레이터 ── */}
            <div id="sec-simulator" style={{ scrollMarginTop: 16 }}>
              <InteractiveSimulator portfolio={result} />
            </div>

            {/* ── MPT 효율적 프론티어 ── */}
            <div id="sec-frontier" style={{ scrollMarginTop: 16 }}>
              <EfficientFrontierChart portfolio={result} />
            </div>

            {/* ── 포트폴리오 비교 ── */}
            <div id="sec-compare" style={{ scrollMarginTop: 16 }}>
              <CompareView portfolio={result} />
            </div>

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

            </>)}

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
