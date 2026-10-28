/**
 * BacktestChart — 백테스팅 연도별 수익률 차트
 *
 * 사용법:
 *   <BacktestChart portfolio={result} startYear={2015} endYear={2024} />
 *
 *   portfolio: POST /api/portfolio/recommend 응답 전체
 *   startYear / endYear: 백테스트 기간 (기본 2015~2024)
 *
 * 동작:
 *   마운트 시 POST /api/portfolio/backtest 를 자체 호출해 데이터를 가져온다.
 *   portfolio.recommendations 가 없으면 렌더링 안 함.
 *
 * 차트 구성:
 *   - 상단 카드: CAGR / MDD / Sharpe 3개 요약
 *   - ComposedChart:
 *       Bar  — 포트폴리오 연도별 수익률 (양수=빨강, 음수=파랑: 한국 관례, Cell 기반)
 *       Line — KOSPI 수익률 (노랑 점선)
 *       Line — S&P 500 수익률 (보라 점선)
 *   - 커스텀 툴팁: 연도/포트폴리오/KOSPI/S&P500 + KOSPI 대비 초과수익
 */
import { useState, useEffect } from 'react'
import {
  ComposedChart, Bar, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine,
  ResponsiveContainer, Cell,
} from 'recharts'
import api from '../api/client'

// ── 색상 상수 ────────────────────────────────────────────────────
const C = {
  positive:   '#dc2626',   // 빨강 — 양수 수익률 Bar (한국 관례: 상승=빨강)
  negative:   '#2563eb',   // 파랑 — 음수 수익률 Bar (한국 관례: 하락=파랑)
  kospi:      '#f59e0b',   // 노랑 — KOSPI
  sp500:      '#a855f7',   // 보라 — S&P 500
  zero:       '#475569',   // 회색 — 0% 기준선
  cardBg:     'var(--surface)',   // 카드 배경
  cardBorder: 'var(--border)',   // 카드 테두리
  text:       'var(--text)',   // 기본 텍스트
  muted:      'var(--text-sub)',   // 보조 텍스트
  green:      '#10b981',   // 긍정 지표
  amber:      '#f59e0b',   // 경고 지표
}

// ── 커스텀 툴팁 ──────────────────────────────────────────────────
const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null

  const port  = payload.find(p => p.dataKey === 'return_pct')
  const kospi = payload.find(p => p.dataKey === 'kospi_ret')
  const sp500 = payload.find(p => p.dataKey === 'sp500_ret')

  const portVal  = port?.value  ?? null
  const kospiVal = kospi?.value ?? null
  const portColor = portVal === null ? C.muted : portVal >= 0 ? C.positive : C.negative

  const fmt = v => v === null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(1)}%`

  return (
    <div style={{
      background: 'var(--surface)', border: `1px solid ${C.cardBorder}`,
      borderRadius: 10, padding: '10px 14px', fontSize: 12, minWidth: 170,
    }}>
      <div style={{ fontWeight: 700, marginBottom: 8, color: C.text }}>{label}년</div>

      {[
        { label: '포트폴리오', value: portVal,  color: portColor },
        { label: 'KOSPI',      value: kospiVal, color: C.kospi   },
        { label: 'S&P 500',    value: sp500?.value ?? null, color: C.sp500 },
      ].map(({ label: l, value, color }) => (
        <div key={l} style={{
          display: 'flex', justifyContent: 'space-between',
          gap: 20, marginBottom: 3,
        }}>
          <span style={{ color: C.muted }}>{l}</span>
          <span style={{ color, fontWeight: 600 }}>{fmt(value)}</span>
        </div>
      ))}

      {portVal !== null && kospiVal !== null && (
        <div style={{
          marginTop: 6, paddingTop: 6,
          borderTop: `1px solid ${C.cardBorder}`,
          color: portVal > kospiVal ? C.green : C.negative,
          fontSize: 11,
        }}>
          KOSPI 대비 {portVal > kospiVal ? '+' : ''}
          {(portVal - kospiVal).toFixed(1)}%p
        </div>
      )}
    </div>
  )
}

// ── 요약 카드 ────────────────────────────────────────────────────
const StatCard = ({ label, value, color, sub }) => (
  <div style={{
    background: C.cardBg, border: `1px solid ${C.cardBorder}`,
    borderRadius: 12, padding: '14px 18px', flex: 1, minWidth: 100,
  }}>
    <div style={{ fontSize: 11, color: C.muted, marginBottom: 4 }}>{label}</div>
    <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
    {sub && <div style={{ fontSize: 11, color: C.muted, marginTop: 3 }}>{sub}</div>}
  </div>
)

// ── 커스텀 범례 ──────────────────────────────────────────────────
const ChartLegend = () => (
  <div style={{
    display: 'flex', gap: 16, justifyContent: 'center',
    fontSize: 12, color: C.muted, marginTop: 4,
  }}>
    <span><span style={{ color: C.positive, fontWeight: 700 }}>■</span> 포트폴리오(+)</span>
    <span><span style={{ color: C.negative, fontWeight: 700 }}>■</span> 포트폴리오(−)</span>
    <span><span style={{ color: C.kospi,    fontWeight: 700 }}>━</span> KOSPI</span>
    <span><span style={{ color: C.sp500,    fontWeight: 700 }}>━</span> S&P 500</span>
  </div>
)

// ── 메인 컴포넌트 ────────────────────────────────────────────────
export default function BacktestChart({ portfolio, startYear = 2015, endYear = 2024 }) {
  const [backtest, setBacktest] = useState(null)
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  // 포트폴리오 추천 목록이 바뀔 때마다 백테스트 재호출
  useEffect(() => {
    const recs = portfolio?.recommendations
    if (!recs?.length) return

    setLoading(true)
    setError(null)

    api.post('/api/portfolio/backtest', {
      portfolio:  portfolio,
      start_year: startYear,
      end_year:   endYear,
    })
      .then(res => setBacktest(res.data))
      .catch(err => {
        console.error('BacktestChart fetch error:', err)
        setError('백테스트 데이터를 불러오지 못했습니다.')
      })
      .finally(() => setLoading(false))
  }, [portfolio?.recommendations])

  // ── 로딩/에러/빈 데이터 처리 ──
  if (!portfolio?.recommendations?.length) return null

  if (loading) return (
    <div style={{
      padding: '32px', textAlign: 'center', color: C.muted, fontSize: 13,
      background: C.cardBg, borderRadius: 14, border: `1px solid ${C.cardBorder}`,
    }}>
      📊 과거 성과 데이터 계산 중...
    </div>
  )

  if (error) return (
    <div style={{
      padding: '16px', color: '#dc2626', fontSize: 13,
      background: C.cardBg, borderRadius: 14, border: `1px solid ${C.cardBorder}`,
    }}>
      {error}
    </div>
  )

  if (!backtest?.yearly_returns?.length) return null

  // ── 데이터 추출 ──
  const {
    cagr_pct        = 0,
    mdd_pct         = 0,
    sharpe_ratio    = 0,
    grade           = '',
    summary_message = '',
    yearly_returns  = [],
    best_year,
    worst_year,
    vs_kospi_cagr   = 0,
    vs_sp500_cagr   = 0,
  } = backtest

  const data = yearly_returns.map(d => ({
    year:       d.year,
    return_pct: d.return_pct ?? 0,
    kospi_ret:  d.kospi_ret  ?? 0,
    sp500_ret:  d.sp500_ret  ?? 0,
  }))

  // ── 색상 판단 ──
  const fmtPct = (v) => `${v > 0 ? '+' : ''}${Number(v).toFixed(1)}%`

  const cagrColor   = cagr_pct >= 8 ? C.positive : cagr_pct >= 3.5 ? C.amber : C.negative
  const mddColor    = Math.abs(mdd_pct) <= 20 ? C.green
                    : Math.abs(mdd_pct) <= 35  ? C.amber
                    : C.negative
  const sharpeColor = sharpe_ratio >= 1.0 ? C.green
                    : sharpe_ratio >= 0.5  ? C.amber
                    : C.negative

  return (
    <div style={{ width: '100%', color: C.text }}>

      {/* ── 헤더 ── */}
      <div style={{ marginBottom: 14 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span style={{ fontSize: 15, fontWeight: 700 }}>
            과거 성과 분석 ({startYear}–{endYear})
          </span>
          {grade && (
            <span style={{
              fontSize: 11, padding: '2px 8px', borderRadius: 6,
              background: 'var(--surface)', color: C.muted,
              border: `1px solid ${C.cardBorder}`,
            }}>
              {grade}
            </span>
          )}
        </div>
        {summary_message && (
          <div style={{ fontSize: 12, color: C.muted, marginTop: 4 }}>
            {summary_message}
          </div>
        )}
      </div>

      {/* ── 요약 카드 3개 ── */}
      <div style={{ display: 'flex', gap: 10, marginBottom: 18, flexWrap: 'wrap' }}>
        <StatCard
          label="연 복리 수익률 (CAGR)"
          value={fmtPct(cagr_pct)}
          color={cagrColor}
          sub={`KOSPI 대비 ${fmtPct(vs_kospi_cagr)} / S&P500 대비 ${fmtPct(vs_sp500_cagr)}`}
        />
        <StatCard
          label="최대낙폭 (MDD)"
          value={fmtPct(mdd_pct)}
          color={mddColor}
          sub={worst_year ? `최악 ${worst_year.year}년 ${fmtPct(worst_year.return_pct)}` : undefined}
        />
        <StatCard
          label="샤프 비율 (위험 대비 수익성)"
          value={Number(sharpe_ratio).toFixed(2)}
          color={sharpeColor}
          sub={best_year ? `최고 ${best_year.year}년 ${fmtPct(best_year.return_pct)} · 높을수록 위험 대비 수익 우위` : '높을수록 위험 대비 수익 우위'}
        />
      </div>

      {/* ── ComposedChart ── */}
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
          <XAxis
            dataKey="year"
            tick={{ fontSize: 11, fill: C.muted }}
            axisLine={{ stroke: C.cardBorder }}
            tickLine={false}
          />
          <YAxis
            tickFormatter={v => `${v > 0 ? '+' : ''}${v}%`}
            tick={{ fontSize: 11, fill: C.muted }}
            axisLine={false}
            tickLine={false}
            width={50}
          />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />

          {/* 0% 기준선 */}
          <ReferenceLine y={0} stroke={C.zero} strokeWidth={1} />

          {/* 포트폴리오 Bar — Cell로 양/음수 색상 분기 */}
          <Bar dataKey="return_pct" name="포트폴리오" maxBarSize={36} radius={[3, 3, 0, 0]}>
            {data.map((entry, idx) => (
              <Cell
                key={`cell-${idx}`}
                fill={entry.return_pct >= 0 ? C.positive : C.negative}
                fillOpacity={0.85}
              />
            ))}
          </Bar>

          {/* KOSPI 라인 */}
          <Line
            type="monotone"
            dataKey="kospi_ret"
            name="KOSPI"
            stroke={C.kospi}
            strokeWidth={1.5}
            dot={false}
            strokeDasharray="4 3"
          />

          {/* S&P 500 라인 */}
          <Line
            type="monotone"
            dataKey="sp500_ret"
            name="S&P 500"
            stroke={C.sp500}
            strokeWidth={1.5}
            dot={false}
            strokeDasharray="2 2"
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* ── 범례 ── */}
      <ChartLegend />

    </div>
  )
}
