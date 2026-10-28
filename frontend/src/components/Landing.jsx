/**
 * Landing — 첫 화면. 좌측 정렬 제품 소개 + 우측 분석 흐름(실제 파이프라인 단계).
 * 가짜 수치는 쓰지 않는다. 표시되는 숫자는 프로젝트 사실(18단계, 210종목)만.
 *
 * props: onStart / onDemo / onLogin
 */
import Icon from './Icon'

const FLOW = [
  { i: 'dash',  t: '조건 입력',          d: '나이 · 월 투자 · 초기 자금 · 목표 월배당 · 투자 성향' },
  { i: 'why',   t: '거시 환경 판단',      d: '시장 국면(레짐)에 따라 자산군 가중치를 조정' },
  { i: 'recs',  t: '종목 선별 · 비중',    d: '4축 유니버스에서 후보를 고르고 비중을 배분' },
  { i: 'health', t: '위험 · 세금 점검',   d: '배당 삭감 위험, 스트레스 테스트, 2026 ISA·연금 절세' },
  { i: 'mc',    t: 'Monte Carlo · FIRE',  d: 'P10 · P50 · P90 시나리오와 목표 달성 시점 역산' },
  { i: 'ai',    t: '설명 · 검증',         d: 'SHAP 설명, 백테스트, 효율적 프론티어' },
]

export default function Landing({ onStart, onDemo, onLogin }) {
  return (
    <div className="lp">
      <div className="lp-grid">
        <section className="lp-copy">
          <div className="lp-eyebrow">TEAM FINSIGHT · 졸업 프로젝트</div>
          <h1 className="lp-title">목표 월배당에서 거꾸로,<br />내 FIRE 시점을 계산합니다</h1>
          <p className="lp-sub">
            AI 기반 배당·포트폴리오 최적화 시스템. 질문 5개로 포트폴리오 구성, 목표 달성 시점,
            배당 삭감 위험, 절세 전략까지 한 번에 분석합니다.
          </p>
          <div className="lp-cta">
            <button type="button" className="lp-btn primary" onClick={onStart}>내 조건으로 분석 시작</button>
            <button type="button" className="lp-btn ghost" onClick={onDemo}>발표 데모 실행</button>
          </div>
          <dl className="lp-facts">
            <div><dt>18</dt><dd>단계 분석 파이프라인</dd></div>
            <div><dt>210</dt><dd>DART 검증 종목 (2013–2025)</dd></div>
            <div><dt>P10·P50·P90</dt><dd>Monte Carlo 시나리오</dd></div>
          </dl>
          <button type="button" className="lp-login" onClick={onLogin}>로그인 / 회원가입 (포트폴리오 저장·추적)</button>
        </section>

        <aside className="lp-flow" aria-label="분석 흐름">
          <div className="lp-flow-h">분석 흐름</div>
          <ol>
            {FLOW.map((s, n) => (
              <li key={s.t}>
                <span className="lp-step-ic"><Icon name={s.i} size={18} /></span>
                <div>
                  <div className="lp-step-t"><i>{n + 1}</i>{s.t}</div>
                  <div className="lp-step-d">{s.d}</div>
                </div>
              </li>
            ))}
          </ol>
        </aside>
      </div>
    </div>
  )
}
