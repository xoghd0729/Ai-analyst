/**
 * EfficientFrontierChart — MPT 효율적 프론티어 산점도
 *
 * 사용법:
 *   <EfficientFrontierChart portfolio={result} />
 *
 *   portfolio: POST /api/portfolio/recommend 응답 전체
 *   마운트 시 POST /api/portfolio/optimize 를 자체 호출.
 *
 * 차트 구성:
 *   - ScatterChart: 5,000개(다운샘플) 포트폴리오 점 — Sharpe에 따라 색상 그라데이션
 *   - 특수 마커: 최대 Sharpe(★) / 최소 변동성(◆)
 *   - x축: 변동성(%), y축: 기대수익률(%)
 *   - 상단 카드: 최대 Sharpe / 최소 변동성 요약 + 상위 3개 종목
 */
import { useState, useEffect } from 'react'
import {
  ScatterChart, Scatter, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import api from '../api/client'

// ── 색상 상수 ────────────────────────────────────────────────────
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

// ── Sharpe → 점 색상 (저 → 고: 빨강 → 노랑 → 초록) ───────────────
function sharpeColor(sharpe, minS, maxS) {
  if (maxS === minS) return C.muted
  const t = Math.max(0, Math.min(1, (sharpe - minS) / (maxS - minS)))
  // 0 = red (#ef4444), 0.5 = amber (#f59e0b), 1 = green (#10b981)
  if (t < 0.5) {
    const r = Math.round(239 + (245 - 239) * (t * 2))
    const g = Math.round(68  + (158 -  68) * (t * 2))
    const b = Math.round(68  + (11  -  68) * (t * 2))
    return `rgb(${r},${g},${b})`
  } else {
    const tt = (t - 0.5) * 2
    const r = Math.round(245 + (16  - 245) * tt)
    const g = Math.round(158 + (185 - 158) * tt)
    const b = Math.round(11  + (129 -  11) * tt)
    return `rgb(${r},${g},${b})`
  }
}

// ── 커스텀 툴팁 ──────────────────────────────────────────────────
const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null

  return (
    <div style={{
      background: 'var(--surface)', border: `1px solid ${C.cardBorder}`,
      borderRadius: 10, padding: '10px 14px', fontSize: 12,
    }}>
      <div style={{ display: 'flex', gap: 16, justifyContent: 'space-between', marginBottom: 2 }}>
        <span style={{ color: C.muted }}>수익률</span>
        <span style={{ color: C.green, fontWeight: 600 }}>
          {d.return >= 0 ? '+' : ''}{d.return?.toFixed(1)}%
        </span>
      </div>
      <div style={{ display: 'flex', gap: 16, justifyContent: 'space-between', marginBottom: 2 }}>
        <span style={{ color: C.muted }}>변동성</span>
        <span style={{ color: C.amber, fontWeight: 600 }}>{d.volatility?.toFixed(1)}%</span>
      </div>
      <div style={{ display: 'flex', gap: 16, justifyContent: 'space-between' }}>
        <span style={{ color: C.muted }}>Sharpe</span>
        <span style={{ color: C.blue, fontWeight: 600 }}>{d.sharpe?.toFixed(2)}</span>
      </div>
    </div>
  )
}

// ── 최적 포트폴리오 요약 카드 ─────────────────────────────────────
function OptPortCard({ title, icon, data, color }) {
  if (!data) return null
  const { tickers = [], weight_pct = [], expected_return, volatility, sharpe } = data

  // 상위 3 종목 (가중치 높은 순)
  const top3 = tickers
    .map((t, i) => ({ ticker: t, pct: weight_pct[i] ?? 0 }))
    .sort((a, b) => b.pct - a.pct)
    .slice(0, 3)

  return (
    <div style={{
      background: C.cardBg, border: `1px solid ${C.cardBorder}`,
      borderRadius: 12, padding: '14px 16px', flex: 1, minWidth: 0,
    }}>
      <div style={{ fontSize: 12, color: C.muted, marginBottom: 8 }}>
        {icon} {title}
      </div>

      {/* 핵심 지표 */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
        {[
          { label: '기대수익률', value: `${expected_return >= 0 ? '+' : ''}${expected_return?.toFixed(1)}%`, color: C.green },
          { label: '변동성',    value: `${volatility?.toFixed(1)}%`,   color: C.amber },
          { label: 'Sharpe',   value: sharpe?.toFixed(2),             color: color   },
        ].map(({ label, value, color: c }) => (
          <div key={label} style={{
            background: 'var(--surface)', borderRadius: 8,
            padding: '6px 10px', fontSize: 11,
          }}>
            <div style={{ color: C.muted }}>{label}</div>
            <div style={{ color: c, fontWeight: 700, fontSize: 13 }}>{value}</div>
          </div>
        ))}
      </div>

      {/* 상위 종목 */}
      <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>상위 배분</div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {top3.map(({ ticker, pct }) => (
          <span key={ticker} style={{
            background: `${color}18`, border: `1px solid ${color}40`,
            borderRadius: 6, padding: '3px 8px', fontSize: 11,
            color: C.text,
          }}>
            {ticker} {pct?.toFixed(0)}%
          </span>
        ))}
      </div>
    </div>
  )
}

// ── 색상 범례 (하단) ──────────────────────────────────────────────
const ColorLegend = () => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 8,
    justifyContent: 'center', marginTop: 6, fontSize: 11, color: C.muted,
  }}>
    <span>Sharpe 낮음</span>
    <div style={{
      width: 120, height: 6, borderRadius: 3,
      background: 'linear-gradient(to right, #ef4444, #f59e0b, #10b981)',
    }} />
    <span>Sharpe 높음</span>
    <span style={{ marginLeft: 14, color: C.purple }}>★ 최대 Sharpe</span>
    <span style={{ marginLeft: 8, color: C.blue }}>◆ 최소 변동성</span>
  </div>
)

// ── 메인 컴포넌트 ────────────────────────────────────────────────
export default function EfficientFrontierChart({ portfolio }) {
  const [optData, setOptData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    const recs = portfolio?.recommendations
    if (!recs?.length) return

    setLoading(true)
    setError(null)

    api.post('/api/portfolio/optimize', {
      recommendations: recs,
      risk_free_rate:  2.0,
      n_portfolios:    5000,
    })
      .then(res  => setOptData(res.data))
      .catch(err => {
        console.error('EfficientFrontierChart fetch error:', err)
        setError('효율적 프론티어 계산에 실패했습니다.')
      })
      .finally(() => setLoading(false))
  }, [portfolio?.recommendations])

  if (!portfolio?.recommendations?.length) return null

  if (loading) return (
    <div style={{
      padding: 32, textAlign: 'center', color: C.muted, fontSize: 13,
      background: C.cardBg, borderRadius: 14, border: `1px solid ${C.cardBorder}`,
    }}>
      효율적 프론티어 계산 중 (5,000개 포트폴리오 시뮬레이션)...
    </div>
  )

  if (error) return (
    <div style={{
      padding: 16, color: C.red, fontSize: 13,
      background: C.cardBg, borderRadius: 14, border: `1px solid ${C.cardBorder}`,
    }}>
      {error}
    </div>
  )

  if (!optData?.efficient_frontier) return null

  const ef = optData.efficient_frontier
  const { points = [], max_sharpe, min_volatility, valid_tickers = [],
          years, risk_free_rate = 2.0 } = ef

  // Sharpe 범위 (점 색상 계산용)
  const sharpes = points.map(p => p.sharpe)
  const minS = Math.min(...sharpes)
  const maxS = Math.max(...sharpes)

  // 특수 마커 (max_sharpe, min_vol)
  const specialPts = [
    max_sharpe    && { ...max_sharpe,    _type: 'max_sharpe'    },
    min_volatility && { ...min_volatility, _type: 'min_vol'      },
  ].filter(Boolean)

  return (
    <div style={{ width: '100%', color: C.text }}>

      {/* ── 헤더 ── */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 4 }}>
          효율적 프론티어 (MPT)
        </div>
        <div style={{ fontSize: 12, color: C.muted }}>
          {years} · {valid_tickers.length}개 종목 · 5,000개 포트폴리오 시뮬레이션
          · 무위험 수익률 {risk_free_rate}%
        </div>
      </div>

      {/* ── 최적 포트폴리오 카드 2개 ── */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 18, flexWrap: 'wrap' }}>
        <OptPortCard
          title="최대 Sharpe 포트폴리오"
          icon="★"
          data={max_sharpe}
          color={C.purple}
        />
        <OptPortCard
          title="최소 변동성 포트폴리오"
          icon="◆"
          data={min_volatility}
          color={C.blue}
        />
      </div>

      {/* ── 산점도 ── */}
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="0" stroke="#e8ecf4" />
          <XAxis
            dataKey="volatility"
            type="number"
            name="변동성"
            unit="%"
            tick={{ fontSize: 11, fill: C.muted }}
            axisLine={{ stroke: C.cardBorder }}
            tickLine={false}
            label={{ value: '변동성 (%)', position: 'insideBottom', offset: -2,
                     style: { fontSize: 10, fill: C.muted } }}
          />
          <YAxis
            dataKey="return"
            type="number"
            name="기대수익률"
            unit="%"
            tick={{ fontSize: 11, fill: C.muted }}
            axisLine={false}
            tickLine={false}
            width={48}
            label={{ value: '기대수익률 (%)', angle: -90, position: 'insideLeft',
                     offset: 10, style: { fontSize: 10, fill: C.muted } }}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#c8d0dc', strokeDasharray: '3 3' }} />

          {/* 무위험 수익률 기준선 */}
          <ReferenceLine
            y={risk_free_rate}
            stroke={C.muted}
            strokeDasharray="4 2"
            strokeWidth={1}
            label={{ value: `rf ${risk_free_rate}%`, position: 'right',
                     style: { fontSize: 9, fill: C.muted } }}
          />

          {/* 일반 frontier 점들 — 색상은 CSS fill로 개별 설정 */}
          <Scatter
            name="포트폴리오"
            data={points}
            fill={C.muted}
            opacity={0.6}
            shape={(props) => {
              const { cx, cy, payload } = props
              const fill = sharpeColor(payload.sharpe, minS, maxS)
              return <circle cx={cx} cy={cy} r={2.5} fill={fill} opacity={0.55} />
            }}
          />

          {/* 특수 마커 (max_sharpe, min_vol) */}
          <Scatter
            name="최적점"
            data={specialPts}
            shape={(props) => {
              const { cx, cy, payload } = props
              const isMax = payload._type === 'max_sharpe'
              const color = isMax ? C.purple : C.blue
              const symbol = isMax ? '★' : '◆'
              return (
                <text
                  x={cx} y={cy}
                  textAnchor="middle" dominantBaseline="central"
                  fontSize={isMax ? 16 : 13}
                  fill={color}
                  filter="drop-shadow(0 0 3px rgba(0,0,0,0.8))"
                >
                  {symbol}
                </text>
              )
            }}
          />
        </ScatterChart>
      </ResponsiveContainer>

      {/* ── 색상 범례 ── */}
      <ColorLegend />

    </div>
  )
}
