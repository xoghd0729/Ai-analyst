# dividend_events 스키마

파일명: {TICKER}_dividends.json 또는 DB 테이블: dividend_events

| 필드                  | 타입    | 설명                           |
|---------------------|-------|------------------------------|
| ticker              | str   | 종목 식별자                       |
| ex_dividend_date    | str   | 배당락일 YYYY-MM-DD              |
| pay_date            | str   | 지급일 YYYY-MM-DD               |
| amount_per_share    | float | 주당 배당금 (현지 통화)               |
| currency            | str   | USD / KRW                    |
| frequency           | str   | monthly / quarterly / annual |
| source              | str   | yahoo / dart / manual        |
| fetched_at          | str   | 수집 시각 ISO8601                |

주의:
- 연간 배당금 = 최근 4회(분기) 또는 12회(월배당) 합산 — 단순 ×4 금지
- ETF 분배금과 개별주 배당은 같은 스키마, frequency로 구분
- 배당락일 기준으로 저장 (지급일 아님)
