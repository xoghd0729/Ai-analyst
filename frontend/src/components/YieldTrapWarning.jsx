export default function YieldTrapWarning({ yieldTraps = [] }) {
  if (!yieldTraps.length) return null

  return (
    <div
      style={{
        background: '#2b0d0d',
        border: '1px solid #7f1d1d',
        borderRadius: 14,
        padding: '16px 18px',
        marginBottom: 14,
      }}
    >
      <div style={{ color: '#fecaca', fontSize: 14, fontWeight: 700, marginBottom: 10 }}>
        Yield Trap 경고
      </div>
      <div style={{ color: '#fee2e2', fontSize: 13, marginBottom: 12 }}>
        이 종목은 배당은 높지만 주가가 빠지고 있어요.
      </div>

      <div style={{ display: 'grid', gap: 8 }}>
        {yieldTraps.map((trap, idx) => (
          <div
            key={`${trap.ticker}-${idx}`}
            style={{
              background: '#3b1414',
              border: '1px solid #991b1b',
              borderRadius: 10,
              padding: '10px 12px',
            }}
          >
            <div style={{ color: '#fff1f2', fontWeight: 700, fontSize: 13 }}>
              {trap.name} ({trap.ticker}) · {trap.severity}
            </div>
            <div style={{ color: '#fecaca', fontSize: 12, marginTop: 4 }}>
              {trap.reason}
            </div>
            {!!trap.alternative_tickers?.length && (
              <div style={{ color: '#fda4af', fontSize: 12, marginTop: 6 }}>
                대안: {trap.alternative_tickers.slice(0, 2).join(', ')}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
