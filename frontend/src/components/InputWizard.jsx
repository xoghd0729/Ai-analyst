/**
 * InputWizard — 투자 조건 설정. 좌측: 단계별 입력 / 우측: 입력값 요약(계산은 단순 곱셈만).
 * 질문 1개당 화면 1개. Enter / 다음 버튼으로 진행, 마지막에서 추천 실행.
 *
 * props: form, onChange(key,val), onSubmit(), onPersona(persona), demo, personas, loading, error, phase, wakeSec
 */
import { useState, useEffect } from 'react'
import { fmtMan } from '../utils/format'
import AnalysisProgress from './AnalysisProgress'
import Icon from './Icon'

const STEPS = [
  { key: 'age', label: '나이', title: '현재 나이를 입력해 주세요', hint: 'FIRE 달성 시점과 생애주기 분석에 사용됩니다.',
    unit: '세', min: 18, max: 80, chips: [25, 30, 35, 40, 50] },
  { key: 'monthly_invest', label: '월 투자', title: '매달 투자 가능한 금액은 얼마인가요?', hint: '월급에서 저축·투자하는 금액입니다.',
    unit: '만원', min: 0, max: 5000, chips: [30, 50, 100, 200, 300], growth: true },
  { key: 'reserve', label: '초기 자금', title: '지금 바로 투자할 수 있는 금액은요?', hint: '예·적금 해지 후 가능한 금액을 포함하고, 없으면 0을 입력하세요.',
    unit: '만원', min: 0, max: 500000, chips: [0, 1000, 5000, 10000, 30000] },
  { key: 'monthly_target', label: '목표 월배당', title: '배당으로 매달 받고 싶은 금액은요?', hint: '생활비 기준으로 생각해 보세요. (예: 150~300만원)',
    unit: '만원/월', min: 10, max: 2000, chips: [100, 150, 200, 300, 500] },
  { key: 'risk_tolerance', label: '투자 성향', title: '투자 성향을 선택해 주세요', hint: '손실을 어느 정도까지 감내할 수 있는지 기준입니다.', risk: true },
]

const RISKS = [
  { value: 'conservative', label: '안정형', desc: '우량 종목 위주 · 배당 안정성 최우선' },
  { value: 'moderate',     label: '중립형', desc: '안정성과 수익률의 균형' },
  { value: 'aggressive',   label: '공격형', desc: 'Total Return 극대화 · 성장 ETF 포함' },
]
const GROWTHS = [{ v: 0, l: '고정' }, { v: 3, l: '연 3%' }, { v: 5, l: '연 5%' }, { v: 8, l: '연 8%' }]
const riskLabel = (v) => RISKS.find(r => r.value === v)?.label || '—'
const won = (v) => (v === '' || v == null || isNaN(Number(v)) ? '—' : fmtMan(Number(v)))

export default function InputWizard({ form, onChange, onSubmit, onPersona, demo, personas, loading, error, phase, wakeSec }) {
  const [step, setStep] = useState(0)          // 0 = 시작 방식 선택, 1~5 = 입력 단계
  const cur = step > 0 ? STEPS[step - 1] : null
  const last = step === STEPS.length

  const next = () => { if (last) onSubmit(); else setStep(s => s + 1) }
  const prev = () => setStep(s => Math.max(0, s - 1))

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Enter' && step > 0 && !loading) { e.preventDefault(); next() } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const rows = [
    { k: 'age',            l: '나이',        v: form.age === '' ? '—' : `${form.age}세` },
    { k: 'monthly_invest', l: '월 투자',     v: won(form.monthly_invest) },
    { k: 'reserve',        l: '초기 자금',   v: won(form.reserve) },
    { k: 'monthly_target', l: '목표 월배당', v: won(form.monthly_target) },
    { k: 'risk_tolerance', l: '투자 성향',   v: riskLabel(form.risk_tolerance) },
  ]

  return (
    <div className="iw">
      <div className="iw-grid">
        {/* ── 좌측: 입력 ── */}
        <section className="iw-main">
          <div className="iw-progress" aria-label="진행 상태">
            <div className="iw-progress-t"><b>투자 조건 입력</b><span>{step === 0 ? '시작' : `${step} / ${STEPS.length}`}</span></div>
            <div className="iw-bar"><div style={{ width: `${(step / STEPS.length) * 100}%` }} /></div>
          </div>

          {step === 0 && (
            <div className="iw-body">
              <h1 className="iw-title">투자 조건 설정</h1>
              <p className="iw-hint">직접 입력하거나, 준비된 시나리오로 바로 분석 결과를 확인할 수 있어요.</p>

              <button type="button" className="iw-btn primary" onClick={() => setStep(1)}>내 조건 입력하기</button>

              <div className="iw-sub">시나리오로 바로 분석</div>
              <ul className="iw-presets">
                {[demo, ...personas].map(p => (
                  <li key={p.key}>
                    <button type="button" disabled={loading} onClick={() => onPersona(p)}>
                      <span className="iw-p-name">{p.key === demo.key ? '발표 데모' : p.title}</span>
                      <span className="iw-p-desc">{p.label}</span>
                      <span className="iw-p-go"><Icon name="chevR" size={16} /></span>
                    </button>
                  </li>
                ))}
              </ul>
              {error && <div className="iw-error">{error}</div>}
              {loading && <AnalysisProgress phase={phase} wakeSec={wakeSec} />}
            </div>
          )}

          {cur && (
            <div className="iw-body">
              <div className="iw-eyebrow">{cur.label}</div>
              <h1 className="iw-title">{cur.title}</h1>
              <p className="iw-hint">{cur.hint}</p>

              {cur.risk ? (
                <div className="iw-risks">
                  {RISKS.map(r => (
                    <button key={r.value} type="button"
                      className={`iw-risk ${form.risk_tolerance === r.value ? 'on' : ''}`}
                      onClick={() => onChange('risk_tolerance', r.value)}>
                      <b>{r.label}</b><small>{r.desc}</small>
                    </button>
                  ))}
                </div>
              ) : (
                <>
                  <div className="iw-field">
                    <input className="iw-input" type="number" autoFocus min={cur.min} max={cur.max}
                      value={form[cur.key]}
                      onChange={e => onChange(cur.key, e.target.value === '' ? '' : Number(e.target.value))} />
                    <span className="iw-unit">{cur.unit}</span>
                  </div>
                  {cur.unit === '만원' && Number(form[cur.key]) >= 10000 && (
                    <div className="iw-conv">= {fmtMan(form[cur.key])}</div>
                  )}
                  <div className="iw-chips">
                    {cur.chips.map(c => (
                      <button key={c} type="button" className={`iw-chip ${Number(form[cur.key]) === c ? 'on' : ''}`}
                        onClick={() => onChange(cur.key, c)}>
                        {cur.unit === '세' ? `${c}세` : cur.unit === '만원' ? (c === 0 ? '0' : fmtMan(c)) : c.toLocaleString()}
                      </button>
                    ))}
                  </div>
                  {cur.growth && (
                    <div className="iw-growth">
                      <div className="iw-sub">월 투자금 연간 증가율</div>
                      <div className="iw-chips">
                        {GROWTHS.map(g => (
                          <button key={g.v} type="button" className={`iw-chip ${Number(form.invest_growth) === g.v ? 'on' : ''}`}
                            onClick={() => onChange('invest_growth', g.v)}>{g.l}</button>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              {error && <div className="iw-error">{error}</div>}
              {loading && last && <AnalysisProgress phase={phase} wakeSec={wakeSec} />}

              <div className="iw-nav">
                <button type="button" className="iw-btn ghost" onClick={prev}>이전</button>
                <button type="button" className="iw-btn primary" onClick={next} disabled={loading}>
                  {last ? (loading ? '분석 중...' : '포트폴리오 분석하기') : '다음'}
                </button>
                <span className="iw-key">Enter ↵</span>
              </div>
            </div>
          )}
        </section>

        {/* ── 우측: 입력값 요약 ── */}
        <aside className="iw-side" aria-label="입력 조건 요약">
          <div className="iw-side-h">입력한 조건</div>
          <dl className="iw-rows">
            {rows.map(r => (
              <div key={r.k} className={cur && cur.key === r.k ? 'on' : ''}>
                <dt>{r.l}</dt><dd>{r.v}</dd>
              </div>
            ))}
          </dl>
        </aside>
      </div>
    </div>
  )
}
