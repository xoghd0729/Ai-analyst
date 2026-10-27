/**
 * InputWizard — 큰 글씨 한 화면씩 넘기는 입력 마법사
 *
 * 질문 1개당 화면 1개. Enter / 다음 버튼으로 진행, 마지막에서 추천 실행.
 * 계산은 하지 않고 form 값만 모아서 onSubmit 으로 넘긴다.
 *
 * props:
 *   form        { age, monthly_invest, reserve, monthly_target, risk_tolerance, invest_growth }
 *   onChange    (key, value) => void
 *   onSubmit    () => void
 *   onPersona   (persona) => void   // 데모/페르소나 즉시 실행
 *   demo        발표 데모 시나리오 객체
 *   personas    페르소나 목록
 *   loading     boolean
 *   error       string | null
 */
import { useState, useEffect } from 'react'
import { fmtMan } from '../utils/format'

const STEPS = [
  {
    key: 'age', title: '지금 몇 살이세요?', hint: 'FIRE 달성 시점과 생애주기 분석에 사용돼요',
    unit: '세', min: 18, max: 80, chips: [25, 30, 35, 40, 50],
  },
  {
    key: 'monthly_invest', title: '매달 얼마를 투자할 수 있나요?', hint: '월급에서 저축·투자하는 금액이에요',
    unit: '만원', min: 0, max: 5000, chips: [30, 50, 100, 200, 300], growth: true,
  },
  {
    key: 'reserve', title: '지금 바로 넣을 수 있는 돈은요?', hint: '예금·적금 해지 후 가능한 금액 포함, 없으면 0',
    unit: '만원', min: 0, max: 500000, chips: [0, 1000, 5000, 10000, 30000],
  },
  {
    key: 'monthly_target', title: '배당으로 매달 얼마를 받고 싶나요?', hint: '생활비 기준으로 생각해 보세요 (예: 150~300만원)',
    unit: '만원/월', min: 10, max: 2000, chips: [100, 150, 200, 300, 500],
  },
  {
    key: 'risk_tolerance', title: '투자 성향은 어떤 편인가요?', hint: '손실을 얼마나 견딜 수 있는지 골라 주세요', risk: true,
  },
]

const RISKS = [
  { value: 'conservative', label: '안정형', desc: '우량 종목 위주 · 배당 안정성 최우선' },
  { value: 'moderate',     label: '중립형', desc: '안정성과 수익률 균형' },
  { value: 'aggressive',   label: '공격형', desc: 'Total Return 극대화 · 성장 ETF 포함' },
]

const GROWTHS = [
  { v: 0, l: '고정' }, { v: 3, l: '보수 3%' }, { v: 5, l: '평균 5%' }, { v: 8, l: '고성장 8%' },
]

export default function InputWizard({ form, onChange, onSubmit, onPersona, demo, personas, loading, error }) {
  const [step, setStep] = useState(0)          // 0 = 시작 화면, 1~5 = 질문
  const cur = step > 0 ? STEPS[step - 1] : null
  const last = step === STEPS.length

  const next = () => { if (last) onSubmit(); else setStep(s => s + 1) }
  const prev = () => setStep(s => Math.max(0, s - 1))

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Enter' && step > 0 && !loading) { e.preventDefault(); next() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  return (
    <div className="wz">
      {/* 진행 점 */}
      <div className="wz-dots" aria-hidden="true">
        {[0, ...STEPS.map((_, i) => i + 1)].map(i => (
          <span key={i} className={`wz-dot ${i === step ? 'on' : i < step ? 'done' : ''}`} />
        ))}
      </div>

      {step === 0 && (
        <div className="wz-body">
          <div className="wz-eyebrow">FINSIGHT · AI 현금흐름 운영체제</div>
          <h1 className="wz-title">목표 월배당에서 거꾸로,<br />내 FIRE 시점을 계산해요</h1>
          <p className="wz-hint">질문 5개에 답하면 포트폴리오·달성 시점·위험·절세까지 한 번에 보여드려요</p>

          <div className="wz-actions">
            <button type="button" className="wz-btn primary big" onClick={() => setStep(1)}>
              내 정보로 시작하기 →
            </button>
          </div>

          <div className="wz-sub">또는 예시로 바로 보기</div>
          <div className="wz-personas">
            <button type="button" className="wz-persona demo" disabled={loading} onClick={() => onPersona(demo)}>
              <span className="wz-pi">🎬</span>
              <span><b>발표 데모</b><small>{demo.label}</small></span>
            </button>
            {personas.map(p => (
              <button key={p.key} type="button" className="wz-persona" disabled={loading} onClick={() => onPersona(p)}>
                <span className="wz-pi">{p.icon}</span>
                <span><b>{p.title}</b><small>{p.label}</small></span>
              </button>
            ))}
          </div>
          {loading && <div className="wz-loading">⏳ 분석 중... 잠시만 기다려 주세요</div>}
        </div>
      )}

      {cur && (
        <div className="wz-body">
          <div className="wz-eyebrow">질문 {step} / {STEPS.length}</div>
          <h1 className="wz-title">{cur.title}</h1>
          <p className="wz-hint">{cur.hint}</p>

          {cur.risk ? (
            <div className="wz-risks">
              {RISKS.map(r => (
                <button key={r.value} type="button"
                  className={`wz-risk ${form.risk_tolerance === r.value ? 'on' : ''}`}
                  onClick={() => onChange('risk_tolerance', r.value)}>
                  <b>{r.label}</b><small>{r.desc}</small>
                </button>
              ))}
            </div>
          ) : (
            <>
              <div className="wz-field">
                <input
                  className="wz-input" type="number" autoFocus
                  min={cur.min} max={cur.max}
                  value={form[cur.key]}
                  onChange={e => onChange(cur.key, e.target.value === '' ? '' : Number(e.target.value))}
                />
                <span className="wz-unit">{cur.unit}</span>
              </div>
              {cur.unit === '만원' && Number(form[cur.key]) >= 10000 && (
                <div className="wz-hint" style={{ margin: '-8px 0 14px' }}>= {fmtMan(form[cur.key])}</div>
              )}
              <div className="wz-chips">
                {cur.chips.map(c => (
                  <button key={c} type="button"
                    className={`wz-chip ${Number(form[cur.key]) === c ? 'on' : ''}`}
                    onClick={() => onChange(cur.key, c)}>
                    {cur.unit === '세' ? `${c}세` : cur.unit === '만원' ? (c === 0 ? '0' : fmtMan(c)) : c.toLocaleString()}
                  </button>
                ))}
              </div>
              {cur.growth && (
                <div className="wz-growth">
                  <div className="wz-sub">월급이 오르면 투자금도 늘리나요? (연 증가율)</div>
                  <div className="wz-chips">
                    {GROWTHS.map(g => (
                      <button key={g.v} type="button"
                        className={`wz-chip ${Number(form.invest_growth) === g.v ? 'on' : ''}`}
                        onClick={() => onChange('invest_growth', g.v)}>
                        {g.l}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {error && <div className="wz-error">{error}</div>}

          <div className="wz-nav">
            <button type="button" className="wz-btn ghost" onClick={prev}>← 이전</button>
            <button type="button" className="wz-btn primary" onClick={next} disabled={loading}>
              {last ? (loading ? '⏳ 분석 중...' : '🚀 포트폴리오 추천받기') : '다음 →'}
            </button>
          </div>
          <div className="wz-keyhint">Enter 키로도 넘어갈 수 있어요</div>
        </div>
      )}
    </div>
  )
}
