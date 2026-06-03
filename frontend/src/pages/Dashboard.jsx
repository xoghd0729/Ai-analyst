import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../api/client'
import './Dashboard.css'

const STATUS = {
  INTACT:    { label: '안전',   emoji: '🟢', cls: 'safe',    desc: '배당 유지 가능성 높음' },
  WEAKENING: { label: '주의',   emoji: '🟡', cls: 'caution', desc: '모니터링 필요' },
  BROKEN:    { label: '위험',   emoji: '🔴', cls: 'danger',  desc: '배당 삭감 위험 감지' },
  // 구 등급 호환
  '🟢 우량': { label: '안전',   emoji: '🟢', cls: 'safe',    desc: '배당 안정성 높음' },
  '🟡 보통': { label: '주의',   emoji: '🟡', cls: 'caution', desc: '추가 확인 필요' },
  '🔴 위험': { label: '위험',   emoji: '🔴', cls: 'danger',  desc: '위험 신호 감지' },
}

function getStatus(item) {
  return STATUS[item.thesis_status] || STATUS[item.grade] || STATUS['🟡 보통']
}

function getRisk(item) {
  // composite_risk: 0~1 (thesis ML 점수, 높을수록 위험)
  // risk: 0~100 (ranking.csv 안전도 점수, 높을수록 안전 → 반전 필요)
  if (item.composite_risk != null) return Math.round(Number(item.composite_risk) * 100)
  if (item.risk != null) return Math.max(0, Math.round(100 - Number(item.risk)))
  return 50
}

function getYield(item) {
  const y = item.yield ?? item.dividend_yield ?? null
  return y ? `${Number(y).toFixed(1)}%` : null
}

const SECTOR_MAP = {
  '005930': '반도체', '000810': '보험', '017670': '통신', '033780': '담배',
  '015760': '에너지', '000270': '자동차', '005380': '자동차', '105560': '은행',
  '055550': '은행', '086790': '은행', '316140': '은행', '024110': '은행',
  '018260': 'IT서비스', '005490': '철강', '068270': '바이오', '030200': '통신',
  '032640': '통신', '000150': '지주', '010950': '정유', '006360': '건설',
  '298020': '화학', '004800': '화학', '082640': '보험', '326030': '바이오',
}

export default function Dashboard() {
  const [items,   setItems]   = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [filter,  setFilter]  = useState('전체')
  const [country, setCountry] = useState('all')  // 'all' | 'kr' | 'us'
  const [search,  setSearch]  = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    setLoading(true)
    Promise.all([
      api.get(`/api/ranking?country=${country}&limit=100`)
         .catch(() => ({ data: { items: [] } })),
      api.get('/api/portfolio/thesis').catch(() => null),
    ]).then(([r, t]) => {
      const rankItems  = r.data?.items || []
      const thesisMap  = {}
      if (t?.data?.all_stocks) {
        t.data.all_stocks.forEach(s => { thesisMap[s.stock_code] = s })
      }
      // thesis 데이터로 enrichment (한국 종목만 thesis 매칭)
      const merged = rankItems.map(item => ({
        ...item,
        ...(item.country !== 'us' ? (thesisMap[item.stock_code] || {}) : {}),
      }))
      setItems(merged)
    })
    .catch(() => setError('서버에 연결할 수 없습니다. FastAPI 서버를 먼저 실행해주세요.'))
    .finally(() => setLoading(false))
  }, [country])

  const filtered = items.filter(item => {
    const st = getStatus(item)
    const filterMatch = filter === '전체' ||
      (filter === '안전' && st.cls === 'safe') ||
      (filter === '주의' && st.cls === 'caution') ||
      (filter === '위험' && st.cls === 'danger')
    const searchMatch = !search ||
      (item.name || '').includes(search) ||
      (item.stock_code || '').includes(search)
    return filterMatch && searchMatch
  })

  const safeCount    = items.filter(i => getStatus(i).cls === 'safe').length
  const cautionCount = items.filter(i => getStatus(i).cls === 'caution').length
  const dangerCount  = items.filter(i => getStatus(i).cls === 'danger').length

  if (loading) return (
    <div className="loading-screen">
      <div className="loading-spinner" />
      <p>배당주 데이터 불러오는 중...</p>
    </div>
  )
  if (error) return (
    <div className="error-screen">
      <div className="error-icon">⚠️</div>
      <p>{error}</p>
    </div>
  )

  return (
    <div className="db-root">
      {/* ── 헤더 ── */}
      <div className="db-header">
        <div className="db-header-inner">
          <div>
            <h1 className="db-title">배당주 건강 리포트</h1>
            <p className="db-subtitle">AI가 매일 분석하는 배당 안전성 모니터</p>
          </div>
          <div className="db-date">{new Date().toLocaleDateString('ko-KR', { month: 'long', day: 'numeric', weekday: 'short' })}</div>
        </div>
      </div>

      <div className="db-content">
        {/* ── 요약 카드 3개 ── */}
        <div className="summary-row">
          <div className="sum-card safe" onClick={() => setFilter(f => f === '안전' ? '전체' : '안전')}>
            <div className="sum-emoji">🟢</div>
            <div className="sum-count">{safeCount}</div>
            <div className="sum-label">안전</div>
            <div className="sum-desc">배당 유지 가능</div>
          </div>
          <div className="sum-card caution" onClick={() => setFilter(f => f === '주의' ? '전체' : '주의')}>
            <div className="sum-emoji">🟡</div>
            <div className="sum-count">{cautionCount}</div>
            <div className="sum-label">주의</div>
            <div className="sum-desc">모니터링 필요</div>
          </div>
          <div className="sum-card danger" onClick={() => setFilter(f => f === '위험' ? '전체' : '위험')}>
            <div className="sum-emoji">🔴</div>
            <div className="sum-count">{dangerCount}</div>
            <div className="sum-label">위험</div>
            <div className="sum-desc">삭감 위험 감지</div>
          </div>
        </div>

        {/* ── 검색 + 필터 ── */}
        <div className="toolbar-row">
          <div className="search-wrap">
            <span className="search-icon">🔍</span>
            <input
              className="search-box"
              placeholder="종목명 검색 (예: 삼성, SCHD)"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
            {search && <button className="search-clear" onClick={() => setSearch('')}>✕</button>}
          </div>
          <div className="filter-pills">
            {['전체', '안전', '주의', '위험'].map(f => (
              <button
                key={f}
                className={`pill ${filter === f ? 'pill-active' : ''} ${f === '안전' ? 'pill-safe' : f === '주의' ? 'pill-caution' : f === '위험' ? 'pill-danger' : ''}`}
                onClick={() => setFilter(f)}
              >{f}</button>
            ))}
          </div>
        </div>

        {/* ── 국가 필터 ── */}
        <div style={{
          display: 'flex', gap: 8, marginBottom: 14,
          alignItems: 'center', flexWrap: 'wrap',
        }}>
          <span style={{ fontSize: 12, color: 'var(--text-sub)', marginRight: 4 }}>
            🌐 국가
          </span>
          {[
            { key: 'all', label: '전체', flag: '🌏' },
            { key: 'kr',  label: '한국', flag: '🇰🇷' },
            { key: 'us',  label: '미국', flag: '🇺🇸' },
          ].map(c => {
            const active = country === c.key
            return (
              <button
                key={c.key}
                onClick={() => setCountry(c.key)}
                style={{
                  padding: '6px 14px',
                  background: active ? 'rgba(79,142,247,.15)' : 'transparent',
                  border: `1px solid ${active ? 'var(--blue)' : 'var(--border)'}`,
                  color: active ? '#60a5fa' : 'var(--text-sub)',
                  borderRadius: 999, fontSize: 12, fontWeight: 600,
                  cursor: 'pointer', transition: 'all 0.15s',
                }}
              >
                {c.flag} {c.label}
              </button>
            )
          })}
        </div>

        {/* ── 종목 카드 그리드 ── */}
        {filtered.length === 0 ? (
          <div className="empty-state">
            <div className="empty-icon">🔍</div>
            <p>검색 결과가 없습니다</p>
          </div>
        ) : (
          <div className="card-grid">
            {filtered.map((item, idx) => {
              const st      = getStatus(item)
              const risk    = getRisk(item)
              const yld     = getYield(item)
              const isUS    = item.country === 'us'
              const sector  = isUS
                ? (item.sector || '미국주식')
                : (SECTOR_MAP[item.stock_code] || '국내주식')
              const isContra = item.contradiction

              return (
                <div
                  key={`${item.country || 'kr'}-${item.stock_code}`}
                  className={`stock-card ${st.cls}`}
                  onClick={() => !isUS && navigate(`/stock/${item.stock_code}`)}
                  style={{ cursor: isUS ? 'default' : 'pointer' }}
                >
                  {/* 카드 상단 */}
                  <div className="sc-top">
                    <div className="sc-left">
                      <div className="sc-rank">
                        #{item.rank || idx + 1}
                        <span style={{
                          marginLeft: 6, fontSize: 11, fontWeight: 600,
                          padding: '1px 6px', borderRadius: 4,
                          background: isUS ? 'rgba(99,102,241,.15)' : 'rgba(239,68,68,.12)',
                          color:      isUS ? '#a5b4fc' : '#fca5a5',
                          border:     `1px solid ${isUS ? 'rgba(99,102,241,.3)' : 'rgba(239,68,68,.25)'}`,
                        }}>
                          {isUS ? '🇺🇸 US' : '🇰🇷 KR'}
                        </span>
                      </div>
                      <div className="sc-name">{item.name}</div>
                      <div className="sc-sector">{sector}</div>
                    </div>
                    <div className={`sc-badge ${st.cls}`}>
                      {st.emoji} {st.label}
                    </div>
                  </div>

                  {/* 배당수익률 */}
                  {yld && (
                    <div className="sc-yield-row">
                      <span className="sc-yield-label">배당수익률</span>
                      <span className="sc-yield-val">{yld}</span>
                    </div>
                  )}

                  {/* 위험도 바 */}
                  <div className="sc-risk-row">
                    <span className="sc-risk-label">배당 안전도</span>
                    <div className="sc-risk-bar-wrap">
                      <div
                        className={`sc-risk-bar ${risk >= 55 ? 'bar-danger' : risk >= 30 ? 'bar-caution' : 'bar-safe'}`}
                        style={{ width: `${Math.min(risk, 100)}%` }}
                      />
                    </div>
                    <span className="sc-risk-pct">{100 - risk}점</span>
                  </div>

                  {/* 한줄 판단 */}
                  <div className="sc-desc">{st.desc}</div>

                  {/* 괴리 배지 */}
                  {isContra && (
                    <div className="sc-contra">⚡ 뉴스↔재무 신호 불일치 — 추가 확인 필요</div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        <p className="db-footer-note">
          * AI 분석 결과는 투자 참고용입니다. 최종 투자 판단은 본인 책임입니다.
        </p>
      </div>
    </div>
  )
}
