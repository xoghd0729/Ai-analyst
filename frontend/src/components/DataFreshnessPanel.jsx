/**
 * DataFreshnessPanel — 데이터 기준일 / 출처 표시
 *
 * Props:
 *   freshness: result.data_freshness (파이프라인 응답의 data_freshness 필드)
 *
 * 레이아웃: 접을 수 있는 작은 info 배너
 *   ▸ 기본: 한 줄 요약 ("데이터 기준일: YYYY-MM-DD · 전체 ✓")
 *   ▸ 펼침: 소스별 날짜·상태 목록
 *
 * 신선도 판정 기준:
 *   - STALE_DAYS(30일) 이상 지난 파일 → ⚠
 *   - 그 이전 → ✓
 *   - "unknown" → —
 */

const STALE_DAYS = 30

// 날짜 문자열 → Date (YYYY-MM-DD)
function parseDate(str) {
  if (!str || str === 'unknown' || str === 'static') return null
  const d = new Date(str)
  return isNaN(d.getTime()) ? null : d
}

// 날짜 → 오늘 기준 경과 일수
function daysAgo(dateStr) {
  const d = parseDate(dateStr)
  if (!d) return null
  return Math.floor((Date.now() - d.getTime()) / 86_400_000)
}

// ✓ / ⚠ / — 판정
function statusOf(dateStr) {
  const days = daysAgo(dateStr)
  if (days === null) return 'unknown'
  return days <= STALE_DAYS ? 'ok' : 'stale'
}

// 표시 텍스트 (날짜 → "YYYY.MM.DD" 형식)
function fmtDate(str) {
  const d = parseDate(str)
  if (!d) return str === 'static' ? '정적 캐시' : '—'
  return `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}.${String(d.getDate()).padStart(2, '0')}`
}

// 소스 메타데이터
const SOURCE_META = {
  kr_stock_ranking: {
    label: '한국주식 랭킹',
    desc:  'DART 공시 기반 점수·배당수익률',
    icon:  '',
  },
  ml_scoring: {
    label: 'ML 위험 점수',
    desc:  'TabPFN Survival 배당컷 위험 추정',
    icon:  '',
  },
  us_stock_scores: {
    label: '미국주식 점수',
    desc:  '2015–2024 정적 수익률 캐시',
    icon:  '',
  },
  etf_quality: {
    label: 'ETF 구성 캐시',
    desc:  'SCHD·VYM·JEPI 등 배당 ETF 정적 구성',
    icon:  '',
  },
  kr_yield_live: {
    label: '한국 배당수익률',
    desc:  'DART/정적 캐시 (pykrx 실시간 미사용)',
    icon:  '',
  },
  dividend_dataset: {
    label: '배당 학습 데이터',
    desc:  'ML 모델 학습 기반 데이터셋',
    icon:  '',
  },
  survival_model: {
    label: 'Survival 모델',
    desc:  'TabPFN 학습 데이터 기준일',
    icon:  '',
  },
  tax_rule: {
    label: '세법 버전',
    desc:  '2026 세법 (ISA 4,000만원/연)',
    icon:  '',
  },
}

// 전체에서 가장 최신 날짜
function latestDate(freshness) {
  const dates = Object.values(freshness)
    .map(v => parseDate(v))
    .filter(Boolean)
  if (!dates.length) return null
  return new Date(Math.max(...dates.map(d => d.getTime())))
}

// 전체 상태: 하나라도 stale이면 ⚠
function overallStatus(freshness) {
  return Object.values(freshness).some(v => statusOf(v) === 'stale') ? 'stale' : 'ok'
}

// ── 색상 팔레트 ──────────────────────────────────────────────────
const C = {
  ok:      '#10b981',   // 초록
  stale:   '#f59e0b',   // 노랑
  unknown: '#94a3b8',   // 회색
  bg:      'var(--surface)',
  bg2:     'var(--surface2)',
  border:  'var(--border)',
  text:    'var(--text)',
  muted:   'var(--text-sub)',
}

const STATUS_ICON = { ok: '✓', stale: '', unknown: '—' }
const STATUS_COLOR = { ok: C.ok, stale: C.stale, unknown: C.unknown }

// ── 한 행 ────────────────────────────────────────────────────────
function SourceRow({ name, dateStr }) {
  const meta   = SOURCE_META[name] || { label: name, desc: '', icon: '' }
  const status = statusOf(dateStr)
  const days   = daysAgo(dateStr)
  const daysStr = days !== null ? ` (${days}일 전)` : ''

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '5px 0', borderBottom: `1px solid ${C.border}`,
    }}>
      
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: C.text }}>{meta.label}</div>
        <div style={{ fontSize: 10, color: C.muted, marginTop: 1, whiteSpace: 'nowrap',
                      overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {meta.desc}
        </div>
      </div>
      <div style={{ textAlign: 'right', minWidth: 90 }}>
        <span style={{ fontSize: 12, color: C.muted }}>{fmtDate(dateStr)}</span>
        <span style={{ fontSize: 11, color: C.muted }}>{daysStr}</span>
      </div>
      <span style={{
        fontSize: 12, fontWeight: 700, minWidth: 14, textAlign: 'center',
        color: STATUS_COLOR[status],
      }}>
        {STATUS_ICON[status]}
      </span>
    </div>
  )
}

// ── 메인 컴포넌트 ────────────────────────────────────────────────
import { useState } from 'react'

export default function DataFreshnessPanel({ freshness }) {
  const [open, setOpen] = useState(false)

  // freshness가 없거나 비어 있으면 렌더링 안 함
  if (!freshness || Object.keys(freshness).length === 0) return null

  // 세법은 항상 고정 추가
  const merged = { ...freshness, tax_rule: '2026' }

  const latest = latestDate(merged)
  const overall = overallStatus(merged)
  const latestStr = latest
    ? `${latest.getFullYear()}.${String(latest.getMonth()+1).padStart(2,'0')}.${String(latest.getDate()).padStart(2,'0')}`
    : '—'

  // 표시할 소스 순서
  const displayOrder = [
    'kr_stock_ranking',
    'kr_yield_live',
    'ml_scoring',
    'us_stock_scores',
    'etf_quality',
    'dividend_dataset',
    'survival_model',
    'tax_rule',
  ]
  const rows = displayOrder.filter(k => merged[k] !== undefined)

  return (
    <div style={{
      background: C.bg,
      border: `1px solid ${C.border}`,
      borderRadius: 10,
      marginBottom: 12,
      overflow: 'hidden',
      fontSize: 12,
    }}>
      {/* ── 헤더 (항상 표시) ── */}
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 8,
          padding: '8px 14px', background: 'transparent', border: 'none',
          cursor: 'pointer', color: C.text,
        }}
      >
        <span style={{
          fontSize: 11, fontWeight: 700, padding: '2px 7px', borderRadius: 5,
          background: overall === 'ok' ? 'rgba(16,185,129,.12)' : 'rgba(245,158,11,.12)',
          color: overall === 'ok' ? C.ok : C.stale,
          border: `1px solid ${overall === 'ok' ? 'rgba(16,185,129,.3)' : 'rgba(245,158,11,.3)'}`,
        }}>
          {overall === 'ok' ? '✓ 데이터 정상' : '일부 오래됨'}
        </span>
        <span style={{ color: C.muted, fontSize: 11 }}>
          기준일 {latestStr} · DART/정적 캐시 기반
        </span>
        <span style={{ marginLeft: 'auto', color: C.muted, fontSize: 10 }}>
          {open ? '▲' : '▼'}
        </span>
      </button>

      {/* ── 펼침: 소스별 목록 ── */}
      {open && (
        <div style={{ padding: '4px 14px 10px', background: C.bg2 }}>
          {/* 면책 노트 */}
          <div style={{
            fontSize: 10, color: C.muted, padding: '6px 0 8px',
            borderBottom: `1px solid ${C.border}`, marginBottom: 6,
          }}>
            한국주식은 DART 공시 기반 정적 캐시입니다.
            pykrx 실시간 시세는 연동하지 않습니다.
            미국주식·ETF는 2015–2024 정적 수익률 데이터를 사용합니다.
          </div>

          {rows.map(k => (
            <SourceRow key={k} name={k} dateStr={String(merged[k])} />
          ))}

          {/* 범례 */}
          <div style={{
            display: 'flex', gap: 14, marginTop: 8,
            fontSize: 10, color: C.muted,
          }}>
            <span><span style={{ color: C.ok, fontWeight: 700 }}>✓</span> 30일 이내</span>
            <span><span style={{ color: C.stale, fontWeight: 700 }}></span> 30일 초과</span>
            <span><span style={{ color: C.unknown, fontWeight: 700 }}>—</span> 날짜 미확인</span>
          </div>
        </div>
      )}
    </div>
  )
}
