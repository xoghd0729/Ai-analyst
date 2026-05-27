import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import api from '../api/client'
import './StockDetail.css'

const BUSINESS_DESC = {
  '005930': { biz: '반도체 · 스마트폰', desc: '메모리 반도체와 갤럭시 스마트폰으로 전 세계 시장을 이끄는 기업입니다.' },
  '000810': { biz: '손해보험',          desc: '자동차·화재보험이 주수입. 보험료와 투자이익으로 안정적 수익을 냅니다.' },
  '017670': { biz: '통신',              desc: '매달 들어오는 통신요금이 주수입. 경기 영향을 적게 받는 방어주입니다.' },
  '033780': { biz: '담배',              desc: '국내 담배 시장의 독점적 지위. 규제 산업이라 진입장벽이 높습니다.' },
  '015760': { biz: '전력 공급',         desc: '국내 전력 독점 공급 기업. 요금은 규제받지만 안정적 수요가 있습니다.' },
  '000270': { biz: '자동차',            desc: '기아차·제네시스로 세계 시장 판매. 전기차 전환이 핵심 변수입니다.' },
  '005380': { biz: '자동차 · 수소',     desc: '현대차그룹 본사. 수소차·전기차 등 미래 모빌리티에 투자 중입니다.' },
  '105560': { biz: '은행 · 금융지주',   desc: 'KB국민은행 중심 금융지주. 예금·대출 이자차익이 핵심 수익원입니다.' },
  '055550': { biz: '은행 · 금융지주',   desc: '신한은행 중심 금융지주. 국내외 균형 잡힌 사업 구조입니다.' },
  '086790': { biz: '은행 · 금융지주',   desc: '하나은행 중심 금융지주. 외환 분야 강점을 가지고 있습니다.' },
  '316140': { biz: '은행 · 금융지주',   desc: '우리은행 중심 금융지주. 주주환원 강화 중인 기업입니다.' },
  '024110': { biz: '은행',              desc: '기업은행. 중소기업 대출 전문. 정부 지원을 받아 배당이 안정적입니다.' },
  '018260': { biz: 'IT서비스 · 물류',   desc: '삼성그룹의 IT 인프라와 물류를 담당. 안정적인 그룹 매출이 기반입니다.' },
  '005490': { biz: '철강 · 2차전지',    desc: '포스코 지주사. 철강 세계 6위. 배터리 소재로 사업 전환 중입니다.' },
  '068270': { biz: '바이오 · 의약품',   desc: '항체의약품 복제약 글로벌 1위. 미국·유럽 판매 확대가 실적 핵심입니다.' },
  '030200': { biz: '통신',              desc: 'KT 통신 서비스. 유·무선·인터넷 통합 통신사. AI 사업 확장 중입니다.' },
  '032640': { biz: '통신',              desc: 'LG유플러스. 5G·IPTV가 매출 축. 통신 3사 중 배당수익률 상위입니다.' },
}
const DEFAULT_BIZ = { biz: '국내 배당주', desc: 'KRX 고배당 지수 편입 종목입니다.' }

function fmtKRW(v) {
  if (!v && v !== 0) return '정보 없음'
  const n = Number(v)
  if (Math.abs(n) >= 1e12) return `${(n/1e12).toFixed(1)}조원`
  if (Math.abs(n) >= 1e8)  return `${(n/1e8).toFixed(0)}억원`
  return `${n.toLocaleString()}원`
}

// thesis_status → 사용자 언어 변환
const THESIS_STATUS = {
  INTACT:    { label: '배당이 안전합니다',       cls: 'safe',    bg: '#D1FAE5', color: '#065F46', emoji: '🟢' },
  WEAKENING: { label: '주의가 필요합니다',       cls: 'caution', bg: '#FEF3C7', color: '#92400E', emoji: '🟡' },
  BROKEN:    { label: '배당 위험 신호 감지',     cls: 'danger',  bg: '#FEE2E2', color: '#991B1B', emoji: '🔴' },
}

// ─────────────────────────────────────────────────────────
// 핵심: 재무지표 + 뉴스 이벤트 → 구체적인 위험 요인 목록 생성
// 초보자가 "왜 위험한가"를 바로 이해할 수 있는 언어로 변환
// ─────────────────────────────────────────────────────────
const NEWS_EVENT_LABEL = {
  dividend_cut:        { icon: '✂️', text: '배당 삭감 또는 중단 결정이 뉴스에서 감지됐습니다.' },
  rights_offering:     { icon: '📢', text: '유상증자가 감지됐습니다. 주식을 새로 발행해 주주 가치가 희석될 수 있습니다.' },
  earnings_shock:      { icon: '📉', text: '실적 쇼크가 보도됐습니다. 배당 재원인 이익이 급감했을 수 있습니다.' },
  guidance_cut:        { icon: '⚠️', text: '향후 실적 전망이 하향 조정됐습니다. 배당 여력 감소가 우려됩니다.' },
  restructuring:       { icon: '🏗️', text: '구조조정·사업 매각 뉴스가 있습니다. 재무 구조 변화에 주의가 필요합니다.' },
  debt_increase:       { icon: '💳', text: '부채 급증 또는 신용등급 하락이 보도됐습니다. 재무 건전성 악화 신호입니다.' },
  fcf_decline:         { icon: '🔻', text: '잉여현금흐름(FCF) 감소 뉴스가 있습니다. 배당 지급 여력이 줄고 있습니다.' },
  dividend_maintained: { icon: '✅', text: '배당 유지 발표가 있었습니다. 긍정적인 신호입니다.' },
  dividend_increase:   { icon: '📈', text: '배당 증가 결정이 발표됐습니다. 주주환원 강화 신호입니다.' },
  share_buyback:       { icon: '🔄', text: '자사주 매입 발표가 있었습니다. 주주 가치 제고 신호입니다.' },
}

function getRiskFactors(metrics, thesis) {
  const factors = []
  if (!metrics && !thesis) return factors

  const get = k => metrics?.[k]?.value ?? null
  const fcf      = get('fcf')
  const coverage = get('dividend_coverage')
  const payout   = get('payout_ratio')
  const opIncome = get('op_income')
  const divPaid  = get('dividends_paid')

  // ── 재무지표 기반 위험 요인 ──────────────────────────────

  // 1. FCF 마이너스 — 가장 심각
  if (fcf !== null && Number(fcf) < 0) {
    factors.push({
      level: 'danger',
      icon: '🔴',
      title: '현금이 부족합니다',
      detail: `잉여현금흐름(FCF)이 ${fmtKRW(fcf)}로 마이너스입니다. 배당금을 지급할 실제 현금이 없다는 뜻으로, 차입금이나 자산 매각으로 배당을 유지하고 있을 가능성이 있습니다.`,
      action: '배당 삭감 가능성이 높으니 주의 깊게 모니터링하세요.',
    })
  }

  // 2. 배당성향 과도 — 이익 대부분을 배당으로
  if (payout !== null && Number(payout) > 75) {
    const p = Number(payout).toFixed(0)
    factors.push({
      level: Number(payout) > 100 ? 'danger' : 'caution',
      icon: Number(payout) > 100 ? '🔴' : '🟡',
      title: `이익의 ${p}%를 배당으로 지급 중`,
      detail: Number(payout) > 100
        ? `이익보다 더 많은 금액을 배당으로 지급하고 있습니다. 이는 지속 불가능한 구조로, 조만간 배당을 줄여야 할 가능성이 높습니다.`
        : `이익의 ${p}%를 배당으로 사용하고 있습니다. 실적이 조금만 나빠져도 배당을 유지하기 어려울 수 있습니다.`,
      action: '실적 발표 때마다 영업이익 변화를 확인하세요.',
    })
  }

  // 3. 배당 커버리지 1 미만 — 배당 감당 불가
  if (coverage !== null && Number(coverage) < 1) {
    factors.push({
      level: 'danger',
      icon: '🔴',
      title: '현금흐름으로 배당을 감당하기 어렵습니다',
      detail: `배당 커버리지가 ${Number(coverage).toFixed(2)}배입니다. 영업에서 나오는 현금흐름보다 배당 지급액이 더 많다는 의미로, 배당 재원이 부족한 상태입니다.`,
      action: '다음 배당 발표 때 금액이 줄어들 수 있습니다.',
    })
  } else if (coverage !== null && Number(coverage) < 1.5) {
    factors.push({
      level: 'caution',
      icon: '🟡',
      title: '배당 여유가 많지 않습니다',
      detail: `배당 커버리지가 ${Number(coverage).toFixed(2)}배입니다. 배당을 지급할 수는 있지만, 예상치 못한 지출이 생기면 배당이 줄어들 수 있습니다.`,
      action: '영업현금흐름 추이를 분기별로 확인하세요.',
    })
  }

  // 4. 영업손실
  if (opIncome !== null && Number(opIncome) < 0) {
    factors.push({
      level: 'danger',
      icon: '🔴',
      title: '본업에서 손실이 나고 있습니다',
      detail: `영업이익이 ${fmtKRW(opIncome)}로 마이너스입니다. 회사가 핵심 사업에서 돈을 벌지 못하고 있다는 뜻으로, 배당을 유지할 재원이 근본적으로 부족한 상황입니다.`,
      action: '다음 분기 실적 개선 여부를 반드시 확인하세요.',
    })
  }

  // ── 뉴스 이벤트 기반 위험 요인 ──────────────────────────

  const dominantEvent = thesis?.dominant_event
  const newsRisk      = thesis?.news_risk ?? 0

  if (dominantEvent && dominantEvent !== 'no_relevant_event') {
    const eventMeta = NEWS_EVENT_LABEL[dominantEvent]
    if (eventMeta) {
      const isNegative = ['dividend_cut','rights_offering','earnings_shock',
                          'guidance_cut','restructuring','debt_increase','fcf_decline']
                          .includes(dominantEvent)
      factors.push({
        level: isNegative ? (newsRisk > 0.4 ? 'danger' : 'caution') : 'good',
        icon: eventMeta.icon,
        title: '최근 뉴스 신호',
        detail: eventMeta.text,
        action: isNegative ? '관련 뉴스를 직접 확인하고 회사 공시를 살펴보세요.' : null,
      })
    }
  }

  // ── 신호 불일치 ──────────────────────────────────────────
  if (thesis?.contradiction) {
    factors.push({
      level: 'caution',
      icon: '⚡',
      title: '뉴스와 재무 신호가 서로 다릅니다',
      detail: '최근 뉴스는 긍정적이지만, 재무 지표는 위험 신호를 보내고 있습니다. 뉴스가 실제 재무 상황을 아직 반영하지 못했거나, 재무 개선이 진행 중일 수 있습니다.',
      action: '단기 뉴스보다 분기별 재무제표를 더 신뢰하세요.',
    })
  }

  return factors
}

// 재무 지표 → 신호등 판단
function getDividendHealth(metrics) {
  if (!metrics) return []
  const get = k => metrics[k]?.value ?? null

  const fcf      = get('fcf')
  const coverage = get('dividend_coverage')
  const payout   = get('payout_ratio')

  const items = []

  // 배당 여력 (FCF)
  items.push({
    label: '배당 지급 여력',
    icon: fcf === null ? '⚪' : fcf > 0 ? '🟢' : '🔴',
    cls: fcf === null ? 'neutral' : fcf > 0 ? 'good' : 'bad',
    value: fmtKRW(fcf),
    explain: fcf > 0
      ? '회사에 현금이 충분해서 배당을 지속할 수 있습니다'
      : fcf === null ? '데이터를 불러오는 중입니다'
      : '현금이 부족해서 배당 유지가 어려울 수 있습니다',
  })

  // 배당 안전성 (coverage)
  const covVal = coverage !== null ? Number(coverage) : null
  items.push({
    label: '배당 안전성',
    icon: covVal === null ? '⚪' : covVal >= 2 ? '🟢' : covVal >= 1 ? '🟡' : '🔴',
    cls: covVal === null ? 'neutral' : covVal >= 2 ? 'good' : covVal >= 1 ? 'caution' : 'bad',
    value: covVal !== null ? `${covVal.toFixed(1)}배` : '정보 없음',
    explain: covVal === null ? '데이터를 불러오는 중입니다'
      : covVal >= 2 ? `현금흐름이 배당금의 ${covVal.toFixed(1)}배 — 여유있게 지급 가능`
      : covVal >= 1 ? '배당은 가능하지만 여유가 많지 않습니다'
      : '현금흐름으로 배당을 감당하기 어려운 수준입니다',
  })

  // 배당성향 (payout)
  const payVal = payout !== null ? Number(payout) : null
  items.push({
    label: '이익 중 배당 비율',
    icon: payVal === null ? '⚪' : payVal <= 50 ? '🟢' : payVal <= 75 ? '🟡' : '🔴',
    cls: payVal === null ? 'neutral' : payVal <= 50 ? 'good' : payVal <= 75 ? 'caution' : 'bad',
    value: payVal !== null ? `${payVal.toFixed(0)}%` : '정보 없음',
    explain: payVal === null ? '데이터를 불러오는 중입니다'
      : payVal <= 50 ? `이익의 ${payVal.toFixed(0)}%만 배당 — 인상 여력이 충분합니다`
      : payVal <= 75 ? '이익 대부분을 배당으로 지급 중, 추가 여력은 제한적입니다'
      : '이익보다 많은 배당 지급 — 지속하기 어려울 수 있습니다',
  })

  return items
}

const STATUS_TIMELINE = {
  INTACT:    { label: '안전',   emoji: '🟢', cls: 'safe',    color: '#10B981' },
  WEAKENING: { label: '주의',   emoji: '🟡', cls: 'caution', color: '#F59E0B' },
  BROKEN:    { label: '위험',   emoji: '🔴', cls: 'danger',  color: '#EF4444' },
}

export default function StockDetail() {
  const { code }   = useParams()
  const navigate   = useNavigate()
  const [stock,    setStock]   = useState(null)
  const [thesis,   setThesis]  = useState(null)
  const [metrics,  setMetrics] = useState(null)
  const [history,  setHistory] = useState(null)
  const [loading,  setLoading] = useState(true)
  const [error,    setError]   = useState(null)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.get(`/api/stock/${code}`),
      api.get(`/api/stock/${code}/thesis`).catch(() => null),
      api.get(`/api/stock/${code}/metrics`).catch(() => null),
      api.get(`/api/stock/${code}/thesis/history`).catch(() => null),
    ])
      .then(([s, t, m, h]) => {
        setStock(s.data)
        setThesis(t?.data || null)
        setMetrics(m?.data?.metrics || null)
        setHistory(h?.data || null)
      })
      .catch(() => setError('데이터를 불러올 수 없습니다.'))
      .finally(() => setLoading(false))
  }, [code])

  if (loading) return (
    <div className="loading-screen">
      <div className="loading-spinner" />
      <p>분석 데이터 불러오는 중...</p>
    </div>
  )
  if (error || !stock) return (
    <div className="error-screen">
      <p>⚠️ {error || '데이터가 없습니다.'}</p>
      <button className="back-btn" onClick={() => navigate('/')}>← 목록으로</button>
    </div>
  )

  const bizInfo   = BUSINESS_DESC[code] || DEFAULT_BIZ
  const scores    = stock.scores || {}
  const yld       = stock.yield ?? stock.dividend_yield ?? null
  const thesisSt  = THESIS_STATUS[thesis?.thesis_status] || null
  const isContra  = thesis?.contradiction

  // 점수 기반 fallback status
  const overall   = scores.overall || 0
  const fallbackSt = overall >= 70
    ? THESIS_STATUS.INTACT
    : overall >= 50
    ? THESIS_STATUS.WEAKENING
    : THESIS_STATUS.BROKEN

  const statusInfo = thesisSt || fallbackSt
  const healthItems  = getDividendHealth(metrics)
  const riskFactors  = getRiskFactors(metrics, thesis)

  // ML 위험도 (0~1 → 0~100)
  const mlRisk = thesis?.ml_risk != null
    ? Math.round(thesis.ml_risk * 100)
    : null

  // thesis 텍스트 정리 (pre 태그 없이 readable하게)
  const thesisText = thesis?.content
    ? thesis.content.replace(/\n{3,}/g, '\n\n').trim()
    : null

  return (
    <div className="sd-root">
      {/* ── 상단 네비 ── */}
      <div className="sd-nav">
        <button className="back-btn" onClick={() => navigate('/')}>← 목록으로</button>
      </div>

      <div className="sd-content">
        {/* ── 히어로: 회사 + 핵심 판단 ── */}
        <div className="hero-card">
          <div className="hero-top">
            <div>
              <div className="hero-biz">{bizInfo.biz}</div>
              <h1 className="hero-name">{stock.name}</h1>
              <p className="hero-desc">{bizInfo.desc}</p>
            </div>
            {yld && (
              <div className="hero-yield-box">
                <div className="hero-yield-val">{Number(yld).toFixed(1)}%</div>
                <div className="hero-yield-label">배당수익률</div>
              </div>
            )}
          </div>

          {/* 핵심 판단 배너 */}
          <div className="verdict-banner" style={{ background: statusInfo.bg, color: statusInfo.color }}>
            <span className="verdict-emoji">{statusInfo.emoji}</span>
            <div>
              <div className="verdict-title">{statusInfo.label}</div>
              {thesis?.action && (
                <div className="verdict-action">{thesis.action}</div>
              )}
            </div>
          </div>

          {/* 괴리 알림 */}
          {isContra && (
            <div className="contra-banner">
              ⚡ <strong>신호 불일치 감지:</strong> 최근 뉴스는 긍정적이지만 재무 지표는 위험 신호를 보내고 있습니다. 추가 확인을 권장합니다.
            </div>
          )}
        </div>

        {/* ── 위험 요인 (WEAKENING/BROKEN일 때만 표시) ── */}
        {riskFactors.length > 0 && (statusInfo.cls === 'danger' || statusInfo.cls === 'caution') && (
          <>
            <div className="section-title">
              {statusInfo.cls === 'danger' ? '⚠️ 왜 위험한가요?' : '🔍 무엇을 주의해야 하나요?'}
            </div>
            <div className="risk-factors">
              {riskFactors.map((f, i) => (
                <div key={i} className={`rf-card rf-${f.level}`}>
                  <div className="rf-header">
                    <span className="rf-icon">{f.icon}</span>
                    <span className="rf-title">{f.title}</span>
                  </div>
                  <p className="rf-detail">{f.detail}</p>
                  {f.action && (
                    <div className="rf-action">
                      <span className="rf-action-icon">👉</span> {f.action}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}

        {/* ── 배당 신호등 3개 ── */}
        <div className="section-title">배당 안전 체크</div>
        <div className="health-grid">
          {healthItems.map((item, i) => (
            <div key={i} className={`health-card health-${item.cls}`}>
              <div className="hc-icon">{item.icon}</div>
              <div className="hc-label">{item.label}</div>
              <div className="hc-value">{item.value}</div>
              <div className="hc-explain">{item.explain}</div>
            </div>
          ))}
        </div>

        {/* ── AI 위험도 게이지 ── */}
        {mlRisk !== null && (
          <>
            <div className="section-title">AI 배당 위험도 분석</div>
            <div className="risk-card">
              <div className="risk-left">
                <div className="risk-gauge-wrap">
                  <svg viewBox="0 0 100 60" className="risk-gauge-svg">
                    <path d="M 10 55 A 40 40 0 0 1 90 55" fill="none" stroke="#F1F5F9" strokeWidth="10" strokeLinecap="round"/>
                    <path
                      d="M 10 55 A 40 40 0 0 1 90 55"
                      fill="none"
                      stroke={mlRisk >= 55 ? '#EF4444' : mlRisk >= 30 ? '#F59E0B' : '#10B981'}
                      strokeWidth="10"
                      strokeLinecap="round"
                      strokeDasharray={`${mlRisk * 1.26} 126`}
                    />
                    <text x="50" y="52" textAnchor="middle" fontSize="16" fontWeight="800"
                      fill={mlRisk >= 55 ? '#DC2626' : mlRisk >= 30 ? '#D97706' : '#059669'}>
                      {mlRisk}%
                    </text>
                  </svg>
                  <div className="risk-gauge-label">배당 삭감 위험도</div>
                </div>
              </div>
              <div className="risk-right">
                <div className="risk-verdict">
                  {mlRisk >= 55
                    ? '배당 삭감 가능성이 높습니다. 신중한 판단이 필요합니다.'
                    : mlRisk >= 30
                    ? '배당 유지 가능하나 재무 지표 변화를 꾸준히 확인하세요.'
                    : '재무 지표상 배당이 안정적으로 유지될 가능성이 높습니다.'}
                </div>
                <div className="risk-note">
                  XGBoost AI 모델이 FCF·배당성향·현금흐름 등 7개 재무지표를 분석한 결과입니다.
                </div>
              </div>
            </div>
          </>
        )}

        {/* ── 배당 지급 구조 ── */}
        {metrics && (
          <>
            <div className="section-title">배당이 어떻게 만들어지나요?</div>
            <div className="cashflow-card">
              <div className="cf-step">
                <div className="cf-label">영업으로 번 현금</div>
                <div className="cf-val">{fmtKRW(metrics?.operating_cf?.value)}</div>
              </div>
              <div className="cf-op">−</div>
              <div className="cf-step">
                <div className="cf-label">시설 투자 비용</div>
                <div className="cf-val">{fmtKRW(metrics?.capex?.value)}</div>
              </div>
              <div className="cf-op">=</div>
              <div className={`cf-step cf-fcf ${Number(metrics?.fcf?.value) >= 0 ? 'positive' : 'negative'}`}>
                <div className="cf-label">남은 현금 (FCF)</div>
                <div className="cf-val">{fmtKRW(metrics?.fcf?.value)}</div>
              </div>
              <div className="cf-op">→</div>
              <div className="cf-step cf-div">
                <div className="cf-label">주주에게 지급한 배당</div>
                <div className="cf-val">{fmtKRW(metrics?.dividends_paid?.value)}</div>
              </div>
            </div>
            <p className="cashflow-note">
              남은 현금(FCF)이 배당 지급액보다 클수록 배당이 지속될 가능성이 높습니다.
            </p>
          </>
        )}

        {/* ── Thesis Timeline ── */}
        {history?.history?.length > 0 && (
          <>
            <div className="section-title">📅 AI 판단 변화 이력</div>
            <div className="timeline-card">
              <div className="timeline-legend">
                <span className="tl-legend-item safe">🟢 안전</span>
                <span className="tl-legend-item caution">🟡 주의</span>
                <span className="tl-legend-item danger">🔴 위험</span>
                <span className="tl-legend-note">AI가 매일 분석한 배당 안전 상태 변화입니다</span>
              </div>
              <div className="timeline-list">
                {history.history.map((h, i) => {
                  const st = STATUS_TIMELINE[h.thesis_status] || STATUS_TIMELINE.WEAKENING
                  const isChange = h.status_changed
                  const dateStr = h.created_at?.slice(0, 10) || ''
                  const timeStr = h.created_at?.slice(11, 16) || ''
                  return (
                    <div key={i} className={`tl-item ${st.cls} ${isChange ? 'tl-changed' : ''}`}>
                      {/* 세로 선 + 점 */}
                      <div className="tl-line-wrap">
                        <div className="tl-dot" style={{ background: st.color }} />
                        {i < history.history.length - 1 && <div className="tl-vline" />}
                      </div>
                      {/* 내용 */}
                      <div className="tl-body">
                        <div className="tl-top">
                          <span className="tl-badge" style={{ background: st.color + '22', color: st.color }}>
                            {st.emoji} {st.label}
                          </span>
                          {isChange && <span className="tl-change-tag">상태 변화</span>}
                          <span className="tl-date">{dateStr} {timeStr}</span>
                        </div>
                        {h.explanation && (
                          <p className="tl-explain">{h.explanation}</p>
                        )}
                        {h.dominant_event && h.dominant_event !== 'no_relevant_event' && (
                          <span className="tl-event-tag">
                            {NEWS_EVENT_LABEL[h.dominant_event]?.icon || '📌'} {h.dominant_event}
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </>
        )}

        {/* ── AI 투자의견 ── */}
        {thesisText && (
          <>
            <div className="section-title">AI 상세 분석</div>
            <div className="thesis-card">
              <div className="thesis-body">
                {thesisText.split('\n').map((line, i) =>
                  line.trim() ? <p key={i} className="thesis-line">{line}</p> : <br key={i} />
                )}
              </div>
              {thesis?.created_at && (
                <div className="thesis-date">
                  분석일: {new Date(thesis.created_at).toLocaleDateString('ko-KR')}
                </div>
              )}
            </div>
          </>
        )}

        <p className="sd-footer-note">
          * 이 분석은 AI 기반 참고 정보입니다. 최종 투자 결정은 반드시 본인 판단으로 하시기 바랍니다.
        </p>
      </div>
    </div>
  )
}
