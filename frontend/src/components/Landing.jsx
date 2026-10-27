/**
 * Landing — 첫 화면 (다크 오로라 히어로)
 * 의존성 없이 순수 React + CSS. 21st.dev 의 Aurora Background / Spotlight Card / Bento 패턴을 참고해 직접 구현.
 *
 * props:
 *   onStart  () => void   // 내 정보로 시작
 *   onDemo   () => void   // 발표 데모 바로 실행
 *   onLogin  () => void   // 로그인/회원가입 열기
 */
const STATS = [
  { n: '18', l: '단계 분석 파이프라인', d: '거시 레짐 → 종목 선별 → 비중 → 위험 → 세금' },
  { n: '210', l: 'DART 검증 종목', d: '2013–2025 재무 · 배당 이력 기반 생존 분석' },
  { n: 'P10·P50·P90', l: 'Monte Carlo 시나리오', d: '시장 레짐을 반영한 현금흐름 범위' },
]

const CHIPS = ['FIRE 역산', '배당 삭감 위험', 'SHAP 설명', '2026 ISA 절세', '백테스트', '효율적 프론티어']

function Spot({ children, className = '' }) {
  const move = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`)
    e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`)
  }
  return <div className={`ld-spot ${className}`} onMouseMove={move}>{children}</div>
}

export default function Landing({ onStart, onDemo, onLogin }) {
  return (
    <div className="ld">
      <div className="ld-aurora" aria-hidden="true">
        <span className="ld-blob b1" /><span className="ld-blob b2" /><span className="ld-blob b3" />
        <span className="ld-grid" />
      </div>

      <div className="ld-inner">
        <div className="ld-badge"><i /> TEAM FINSIGHT · 졸업 프로젝트</div>

        <h1 className="ld-title">
          목표 월배당에서 거꾸로,<br />
          <span className="ld-grad">내 FIRE 시점을 설계합니다</span>
        </h1>
        <p className="ld-sub">
          AI 기반 배당·포트폴리오 최적화 시스템 — 질문 5개로 포트폴리오, 달성 시점,
          배당 삭감 위험, 절세 전략까지 한 번에 계산해요.
        </p>

        <div className="ld-cta">
          <button type="button" className="ld-btn primary" onClick={onDemo}>🎬 발표 데모 바로 보기</button>
          <button type="button" className="ld-btn ghost" onClick={onStart}>내 정보로 시작하기 →</button>
        </div>

        <div className="ld-chips">
          {CHIPS.map(c => <span key={c} className="ld-chip">{c}</span>)}
        </div>

        <div className="ld-stats">
          {STATS.map(s => (
            <Spot key={s.l} className="ld-stat">
              <div className="ld-n">{s.n}</div>
              <div className="ld-l">{s.l}</div>
              <div className="ld-d">{s.d}</div>
            </Spot>
          ))}
        </div>

        <button type="button" className="ld-login" onClick={onLogin}>로그인 / 회원가입 (저장·추적 기능)</button>
      </div>
    </div>
  )
}
