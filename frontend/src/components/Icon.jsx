/**
 * Icon — 선형(stroke) SVG 아이콘 세트. 외부 의존성 없음. currentColor 를 따라가므로 CSS 색상으로 제어.
 * 사용: <Icon name="dash" size={18} />
 */
const P = {
  dash:     <><rect x="3" y="3" width="7.5" height="7.5" rx="1.8"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.8"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.8"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.8"/></>,
  why:      <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/></>,
  recs:     <><path d="M9 6h12M9 12h12M9 18h12"/><circle cx="4.5" cy="6" r="1.2" fill="currentColor"/><circle cx="4.5" cy="12" r="1.2" fill="currentColor"/><circle cx="4.5" cy="18" r="1.2" fill="currentColor"/></>,
  alloc:    <><path d="M12 3a9 9 0 1 0 9 9h-9z"/><path d="M15 3.4A9 9 0 0 1 20.6 9H15z"/></>,
  tax:      <><path d="M19 5 5 19"/><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="17" r="2.5"/></>,
  growth:   <><path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/></>,
  fire:     <path d="M12 3c.8 3.6 5 5 5 10a5 5 0 0 1-10 0c0-2 .9-3.2 2-4.2.1 1.7.9 2.7 2 2.9C10.8 8.6 11 5.6 12 3z"/>,
  mc:       <path d="M3 12h3l3 8 4-16 3 8h5"/>,
  sim:      <><path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/></>,
  health:   <path d="M12 3l8 3v6c0 4.8-3.3 7.9-8 9-4.7-1.1-8-4.2-8-9V6z"/>,
  ai:       <><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M19 16l.7 1.8L21.5 18.5l-1.8.7L19 21l-.7-1.8-1.8-.7 1.8-.7z"/></>,
  frontier: <><path d="M3 20c4.5 0 6.5-3 8.5-8S16.5 4 21 4"/><circle cx="8" cy="17" r="1.4" fill="currentColor"/><circle cx="14" cy="8.5" r="1.4" fill="currentColor"/></>,
  compare:  <><path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/></>,
  backtest: <><path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-6"/></>,
  edit:     <><path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17z"/><path d="M14.5 7.5l3 3"/></>,
  save:     <><path d="M5 3h11l4 4v14H5z"/><path d="M8 3v6h7V3M8 21v-7h8v7"/></>,
  chevL:    <path d="M15 5l-7 7 7 7"/>,
  chevR:    <path d="M9 5l7 7-7 7"/>,
  logo:     <><path d="M4 18l5-6 4 3 7-9"/><path d="M15 6h5v5"/></>,
}

export default function Icon({ name, size = 18, strokeWidth = 1.8, className = '' }) {
  return (
    <svg className={`ic ${className}`} width={size} height={size} viewBox="0 0 24 24" fill="none"
         stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {P[name] || P.dash}
    </svg>
  )
}
