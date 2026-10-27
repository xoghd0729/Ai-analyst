// 금액(만원 단위) → 읽기 쉬운 표기. 10,000만원 이상은 억 단위로 표시.
//   5000 → "5,000만원" / 30000 → "3억원" / 125000 → "12억 5,000만원"
export function fmtMan(v) {
  const n = Math.round(Number(v) || 0)
  const neg = n < 0 ? '-' : ''
  const a = Math.abs(n)
  if (a < 10000) return `${neg}${a.toLocaleString('ko-KR')}만원`
  const eok = Math.floor(a / 10000)
  const rest = a % 10000
  return `${neg}${eok.toLocaleString('ko-KR')}억${rest ? ' ' + rest.toLocaleString('ko-KR') + '만' : ''}원`
}
