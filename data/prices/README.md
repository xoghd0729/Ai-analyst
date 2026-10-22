# daily_prices 스키마

파일명: {TICKER}_prices.json 또는 DB 테이블: daily_prices

| 필드           | 타입    | 설명                        |
|--------------|-------|---------------------------|
| ticker       | str   | 종목 식별자 (SCHD, 448290 등)   |
| date         | str   | YYYY-MM-DD                |
| close_price  | float | 종가 (현지 통화)                |
| currency     | str   | USD / KRW                 |
| adjusted     | bool  | 수정주가 여부 (액면분할 반영)         |
| source       | str   | yahoo / dart / manual      |
| fetched_at   | str   | 수집 시각 ISO8601             |

주의:
- 과거 데이터와 최신 데이터를 같은 테이블에 저장, date로 구분
- 수정주가(adjusted=true)를 기본으로 사용
- 출처 명시 필수 — 출처 불명 데이터는 계산에 사용 금지
