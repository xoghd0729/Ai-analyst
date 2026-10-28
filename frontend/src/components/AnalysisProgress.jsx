/**
 * AnalysisProgress — 분석 요청의 실제 단계만 보여주는 진행 표시
 *   phase: 'wake'(서버 연결 확인) | 'analyze'(포트폴리오 분석 실행)
 *   wakeSec: 서버 응답을 기다린 경과 시간(초). 절전 상태에서 깨어나는 중이면 증가한다.
 * 가짜 퍼센트는 쓰지 않는다. 지금 어느 단계를 기다리는지만 알려준다.
 */
const STEPS = [
  { id: 'wake',    label: '서버 연결 확인' },
  { id: 'analyze', label: '포트폴리오 분석 실행' },
]

export default function AnalysisProgress({ phase = 'wake', wakeSec = null }) {
  const idx = Math.max(0, STEPS.findIndex(s => s.id === phase))
  const sleeping = phase === 'wake' && wakeSec != null && wakeSec >= 4

  return (
    <div className="ap" role="status" aria-live="polite">
      <ul className="ap-list">
        {STEPS.map((s, i) => {
          const state = i < idx ? 'done' : i === idx ? 'active' : 'todo'
          return (
            <li key={s.id} className={`ap-item ${state}`}>
              <span className="ap-mark">
                {state === 'done' ? '✓' : state === 'active' ? <i className="ap-spin" /> : ''}
              </span>
              <span className="ap-label">{s.label}</span>
              {state === 'active' && phase === 'wake' && wakeSec != null && wakeSec >= 1 && (
                <span className="ap-time">{wakeSec}초</span>
              )}
            </li>
          )
        })}
      </ul>
      {sleeping && (
        <p className="ap-note">서버가 절전 상태에서 깨어나는 중입니다. 처음 접속하면 1~2분 걸릴 수 있어요.</p>
      )}
      {phase === 'analyze' && (
        <p className="ap-note">입력 조건으로 종목 선정, 시뮬레이션, 세금 계산을 실행하고 있습니다.</p>
      )}
    </div>
  )
}
