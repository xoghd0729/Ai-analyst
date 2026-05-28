import { useEffect, useState } from 'react'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, Cell, ReferenceLine,
} from 'recharts'
import api from '../api/client'

/**
 * BacktestChart — 21년 백테스팅 시각화
 *
 * 역사적 데이터로 "이 추천이 과거에도 통했는가?"를 검증.
 * D2에서 추가된 Sortino/Calmar/IR까지 모두 표시.
 *
 * props:
 *   portfolio  : recommend API 응답 (recommendations + summary 포함)
 *   startYear  : 시작 연도 (기본 2005)
 *   endYear    : 종료 연도 (기본 2024)
 */
export default function BacktestChart({ portfolio, startYear = 2005, endYear = 2024 }) {
  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(false)
  const [error,   setError]   = useState(null)

  useEffect(() => {
    if (!portfolio?.recommendations?.length) return
    let cancelled = false

    const fetchBacktest = async () => {
      setLoading(true); setError(null)
      try {
        const res = await api.post('/api/portfolio/backtest', {
          portfolio,
          start_year: startYear,
          end_year:   endYear,
        })
        if (!cancelled) setData(res.data)
      } catch {
        if (!cancelled) setError('백테스팅 결과를 불러올 수 없습니다.')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchBacktest()
    return () => { cancelled = true }
  }, [portfolio, startYear, endYear])

  // ── 로딩 ─────────────────────────────────────
  if (loading) {
    return (
      <div style={cardStyle}>
        <div style={titleRowStyle}>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>
            📈 21년 백테스팅 — 이 추천이 과거에도 통했는가?
          </div>
        </div>
        <div style={{
          height: 360, display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#64748b', fontSize: 13,
        }}>
          ⏳ 2005~2024 실제 데이터로 시뮬레이션 중...
        </div>
      </div>
    )
  }

  // ── 에러 ─────────────────────────────────────
  if (error) {
    return (
      <div style={cardStyle}>
        <div style={titleRowStyle}>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>
            📈 21년 백테스팅
          </div>
        </div>
        <div style={{
          padding: '40px 20px', textAlign: 'center', color: '#f87171',
          fontSize: 13, background: 'rgba(248,113,113,.05)', borderRadius: 8,
        }}>
          {error}
        </div>
      </div>
    )
  }

  // ── 데이터 없음 ──────────────────────────────
  if (!data || !data.yearly_returns?.length) return null

  // 차트용 데이터 가공
  const chartData = data.yearly_returns.map(yr => ({
    year:        yr.year,
    portfolio:   yr.return_pct ?? 0,
    kospi:       yr.kospi_ret ?? null,
    sp500:       yr.sp500_ret ?? null,
  }))

  // 메트릭 카드 데이터
  const metrics = [
    {
      label: 'CAGR',
      value: data.cagr_pct,
      unit:  '%',
      color: (data.cagr_pct ?? 0) >= 6 ? '#34d399' : (data.cagr_pct ?? 0) >= 3 ? '#fbbf24' : '#f87171',
      desc:  '연복리 수익률',
    },
    {
      label: 'MDD',
      value: data.mdd_pct,
      unit:  '%',
      color: '#f87171',
      desc:  '최대 낙폭',
    },
    {
      label: 'Sharpe',
      value: data.sharpe_ratio,
      unit:  '',
      color: (data.sharpe_ratio ?? 0) >= 1 ? '#34d399' : (data.sharpe_ratio ?? 0) >= 0.5 ? '#fbbf24' : '#f87171',
      desc:  '위험조정 수익률',
    },
    {
      label: 'Sortino',
      value: data.sortino_ratio,
      unit:  '',
      color: (data.sortino_ratio ?? 0) >= 1.5 ? '#34d399' : (data.sortino_ratio ?? 0) >= 0.8 ? '#fbbf24' : '#f87171',
      desc:  '하방위험 조정',
    },
  ]

  return (
    <div style={cardStyle}>
      {/* 타이틀 + 배지 */}
      <div style={titleRowStyle}>
        <div>
          <div style={{ fontSize: 16, fontWeight: 700, color: '#e2e8f0' }}>
            📈 21년 백테스팅 — 이 추천이 과거에도 통했는가?
          </div>
          <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 4 }}>
            2005~2024 실제 데이터 기준 · 2008·2020 위기 포함
          </div>
        </div>
        <div style={{
          padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600,
          background: 'rgba(79,142,247,.15)', color: '#60a5fa',
          border: '1px solid rgba(79,142,247,.35)',
        }}>
          21년 시뮬레이션
        </div>
      </div>

      {/* 메트릭 카드 4개 */}
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10,
        marginTop: 14, marginBottom: 18,
      }}>
        {metrics.map(m => (
          <div key={m.label} style={{
            padding: '12px 14px', background: '#0f172a', borderRadius: 10,
            border: '1px solid #1e293b',
          }}>
            <div style={{
              fontSize: 11, color: '#64748b', fontWeight: 600,
              textTransform: 'uppercase', letterSpacing: 0.5,
            }}>
              {m.label}
            </div>
            <div style={{
              fontSize: 22, fontWeight: 700, color: m.color, marginTop: 2,
              fontVariantNumeric: 'tabular-nums',
            }}>
              {m.value !== null && m.value !== undefined
                ? Number(m.value).toFixed(2)
                : '—'}
              <span style={{ fontSize: 13, fontWeight: 500, marginLeft: 2 }}>{m.unit}</span>
            </div>
            <div style={{ fontSize: 10, color: '#64748b', marginTop: 2 }}>
              {m.desc}
            </div>
          </div>
        ))}
      </div>

      {/* 메인 차트 */}
      <div style={{ height: 320 }}>
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 4 }}>
            <CartesianGrid stroke="#1e293b" strokeDasharray="2 4" />
            <XAxis
              dataKey="year"
              stroke="#64748b"
              tick={{ fontSize: 11, fill: '#94a3b8' }}
            />
            <YAxis
              stroke="#64748b"
              tick={{ fontSize: 11, fill: '#94a3b8' }}
              tickFormatter={(v) => `${v}%`}
            />
            <ReferenceLine y={0} stroke="#475569" strokeWidth={1} />
            <Tooltip
              contentStyle={{
                background: '#0f172a', border: '1px solid #334155', borderRadius: 8,
                fontSize: 12, color: '#e2e8f0',
              }}
              formatter={(value, name) => {
                if (value === null || value === undefined) return ['—', name]
                return [`${Number(value).toFixed(2)}%`, name]
              }}
              labelStyle={{ color: '#94a3b8', fontWeight: 600 }}
            />
            <Legend
              wrapperStyle={{ fontSize: 12, paddingTop: 4 }}
              iconType="rect"
            />
            <Bar
              dataKey="portfolio"
              name="추천 포트폴리오"
              radius={[2, 2, 0, 0]}
              barSize={18}
            >
              {chartData.map((entry, i) => (
                <Cell key={i} fill={entry.portfolio >= 0 ? '#4f8ef7' : '#ef4444'} />
              ))}
            </Bar>
            <Line
              type="monotone"
              dataKey="kospi"
              name="KOSPI"
              stroke="#fbbf24"
              strokeWidth={2}
              dot={{ r: 3, fill: '#fbbf24' }}
              connectNulls
            />
            <Line
              type="monotone"
              dataKey="sp500"
              name="S&P 500"
              stroke="#34d399"
              strokeWidth={2}
              dot={{ r: 3, fill: '#34d399' }}
              connectNulls
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* 하단 인사이트 */}
      {data.summary_message && (
        <div style={{
          marginTop: 14, padding: '10px 14px', background: '#0f172a',
          borderRadius: 8, fontSize: 12, color: '#94a3b8',
          borderLeft: '3px solid #4f8ef7', lineHeight: 1.6,
        }}>
          {data.summary_message}
        </div>
      )}

      {/* 학술 정직성 주석 */}
      <div style={{ marginTop: 10, fontSize: 10, color: '#475569', textAlign: 'right' }}>
        * 일부 ETF(SCHD·DGRO·JEPI 등)의 상장 이전 연도는 동일 카테고리 ETF 수익률로 합성 적용
      </div>
    </div>
  )
}

// ── 스타일 상수 ────────────────────────────────
const cardStyle = {
  background: '#0a1628', borderRadius: 16, padding: '20px 24px',
  border: '1px solid #1e293b', marginTop: 16,
}

const titleRowStyle = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
  gap: 16,
}
