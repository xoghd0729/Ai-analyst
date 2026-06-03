import { BrowserRouter, Routes, Route, NavLink, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard'
import StockDetail from './pages/StockDetail'
import Portfolio from './pages/Portfolio'
import ErrorBoundary from './components/ErrorBoundary'
import './App.css'

export default function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <nav className="navbar">
          <div className="nav-brand">
            <span className="nav-logo">📈</span>
            <span className="nav-title">AI Cashflow OS</span>
          </div>
          <div className="nav-links">
            <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              포트폴리오 설계
            </NavLink>
            <NavLink to="/ranking" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              배당 종목 랭킹
            </NavLink>
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
