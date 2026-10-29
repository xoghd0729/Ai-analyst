/**
 * Landing — 첫 화면. 설명 최소화, 분석 시작으로 바로 유도한다.
 * props: onStart / onDemo / onLogin
 */
export default function Landing({ onStart, onDemo, onLogin }) {
  return (
    <div className="lp">
      <div className="lp-center">
        <div className="lp-eyebrow">FinSight</div>
        <h1 className="lp-title">나의 배당 투자 계획을<br />설계하세요</h1>
        <p className="lp-sub">투자 조건을 입력하면<br />배당 포트폴리오부터 FIRE 달성 전망까지 분석합니다.</p>
        <div className="lp-cta">
          <button type="button" className="lp-btn primary" onClick={onStart}>분석 시작하기</button>
          <button type="button" className="lp-btn ghost" onClick={onDemo}>예시로 바로 보기</button>
        </div>
        <button type="button" className="lp-login" onClick={onLogin}>저장한 포트폴리오가 있다면 로그인</button>
      </div>
    </div>
  )
}
