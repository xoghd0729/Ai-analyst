import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import StockDetail from './pages/StockDetail'
import Portfolio from './pages/Portfolio'
import ErrorBoundary from './components/ErrorBoundary'
import Icon from './components/Icon'
import './App.css'

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <nav className="navbar">
          <div className="nav-brand">
            <span className="nav-logo"><Icon name="logo" size={17} strokeWidth={2.3} /></span>
            <span className="nav-title">AI 기반 배당·포트폴리오 최적화 시스템</span>
          </div>
          <div className="nav-links">
            <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              포트폴리오 설계
            </NavLink>
            {/* 발표용: 랭킹 메뉴 임시 숨김 (50점 라벨 정리 전까지). 페이지/라우트는 그대로 유지 — 발표 후 이 블록만 살리면 복구됨.
            <NavLink to="/ranking" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              배당 종목 랭킹
            </NavLink>
            */}
          </div>
        </nav>

        <main className="main-content">
          <ErrorBoundary>
            <Routes>
              {/* 메인 = AI 포트폴리오 설계 (캡스톤 핵심 데모) */}
              <Route path="/" element={<Portfolio />} />
              {/* 종목 랭킹은 보조 메뉴 */}
              <Route path="/ranking" element={<Dashboard />} />
              {/* 하위 호환: 기존 링크 보호 */}
              <Route path="/portfolio" element={<Navigate to="/" replace />} />
              <Route path="/stock/:code" element={<StockDetail />} />
            </Routes>
          </ErrorBoundary>
        </main>
      </div>
    </BrowserRouter>
  )
}
