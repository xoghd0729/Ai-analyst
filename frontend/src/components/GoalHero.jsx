/**
 * GoalHero — 대시보드 첫 카드 (Betterment "Goal progress" 구조 참고)
 * 왼쪽: 핵심 숫자 하나(달성 나이) + 확률/진행/위험. 오른쪽: 월배당 전망 밴드 차트.
 * 계산은 하지 않는다. 부모가 준 값(fanData 등)만 그린다.
 */
import { ResponsiveContainer, ComposedChart, Area, Line, XAxis, YAxis, Tooltip, ReferenceLine, CartesianGrid } from 'recharts'

const fmtAsset = (m) => (m >= 10000 ? `${(m / 10000).toFixed(1)}억` : `${Math.round(m).toLocaleString()}만`)

function Tip({ active, payload, label }) {
  if (!active || !payload || !payload.length) return null
  const d = payload[0].payload
  return (
    <div className="gh-tip">
      <b>{label}세</b>
      <div>기본 <span>{d.base}만원/월</span></div>
      <div className="mut">비관 {d.low} ~ 낙관 {d.high}</div>
    </div>
  )
}

export default function GoalHero({
  target, achAge, curAge, prob, riskLabel, riskColor, curMonthly, curAsset, targetAsset,
  monthlyInvest, growth, fanData, gap, onGo,
}) {
  const left = achAge ? achAge - curAge : null
  const pctAsset = Math.max(1, Math.min(100, (curAsset / targetAsset) * 100))
  const probColor = prob >= 80 ? '#059669' : prob >= 50 ? '#d97706' : '#dc2626'
  const probText = prob >= 80 ? '달성 가능성 높음' : prob >= 50 ? '달성 가능성 보통' : '달성 가능성 낮음'
  const maxAge = Math.min(75, Math.max((achAge || curAge + 15) + 10, curAge + 15))
  const data = (fanData || []).filter(d => d.age <= maxAge).map(d => ({ ...d, band: [d.low, d.high] }))

  return (
    <div className="gh" id="sec-headline">
      <div className="gh-left">
        <div className="gh-eyebrow">목표 월배당 {target}만원</div>
        <div className="gh-pill" style={{ color: probColor, background: `${probColor}14` }}>
          <i style={{ background: probColor }} />{probText} · {prob}%
        </div>
        <div className="gh-big">{achAge ? achAge : '—'}<small>{achAge ? '세' : ''}</small></div>
        <div className="gh-bigsub">
          {achAge ? `에 월 ${target}만원 배당 달성 예상` : '달성 시점을 계산하지 못했어요'}
        </div>
        <div className="gh-meta">
          {left != null && <span>지금부터 <b>{left}년</b></span>}
          {gap != null && gap > 0 && <span className="ok">목표 시점보다 <b>{gap}년</b> 빠름</span>}
          {gap != null && gap < 0 && <span className="warn">목표 시점보다 <b>{-gap}년</b> 늦음</span>}
        </div>

        <div className="gh-stats">
          <div><span>현재 월배당</span><b>{curMonthly.toFixed(1)}<small>만원</small></b></div>
          <div><span>배당 위험</span><b style={{ color: riskColor }}>{riskLabel}</b></div>
          <div><span>월 투자</span><b>{monthlyInvest}<small>만원</small></b></div>
        </div>

        <div className="gh-prog">
          <div className="gh-prog-h"><span>목표 자산 도달</span><b>{fmtAsset(curAsset)} → {fmtAsset(targetAsset)}</b></div>
          <div className="gh-bar"><div style={{ width: `${pctAsset}%` }} /></div>
        </div>
        <div className="gh-note">가정 기반 추정{growth > 0 ? ` · 연 ${growth}% 증액` : ''} · 배당 재투자 복리</div>
      </div>

      <div className="gh-right">
        <div className="gh-ch">
          <span>월배당 전망</span>
          <span className="gh-legend"><i className="l1" />기본 <i className="l2" />비관~낙관 <i className="l3" />목표</span>
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={data} margin={{ top: 12, right: 18, left: 0, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="#e8edf5" />
            <XAxis dataKey="age" tickLine={false} axisLine={{ stroke: '#e3e8f2' }} tick={{ fontSize: 12, fill: '#64748b' }}
              tickFormatter={v => `${v}세`} />
            <YAxis tickLine={false} axisLine={false} width={48} tick={{ fontSize: 12, fill: '#64748b' }}
              tickFormatter={v => `${v}만`} />
            <Tooltip content={<Tip />} />
            <Area type="monotone" dataKey="band" stroke="none" fill="#2563eb" fillOpacity={0.12} isAnimationActive={false} />
            <ReferenceLine y={target} stroke="#d97706" strokeDasharray="5 4" />
            {achAge && <ReferenceLine x={achAge} stroke="#2563eb" strokeDasharray="3 4" />}
            <Line type="monotone" dataKey="base" stroke="#2563eb" strokeWidth={3} dot={false} isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
        <div className="gh-next">
          <span>다음으로</span>
          <button type="button" onClick={() => onGo('mc')}>Monte Carlo 변동 확인</button>
          <button type="button" onClick={() => onGo('sim')}>조건 바꿔 보기</button>
          <button type="button" onClick={() => onGo('recs')}>추천 종목 보기</button>
        </div>
      </div>
    </div>
  )
}
