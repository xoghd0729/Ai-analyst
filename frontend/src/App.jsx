import { useState } from "react";
import SearchBar from "./components/SearchBar";
import AnalysisResult from "./components/AnalysisResult";
import "./App.css";

const STOCK_LIST = [
  { code: "005930", name: "삼성전자", corp_code: "00126380" },
  { code: "000660", name: "SK하이닉스", corp_code: "00164779" },
  { code: "035420", name: "NAVER", corp_code: "00266961" },
  { code: "005380", name: "현대차", corp_code: "00164742" },
  { code: "051910", name: "LG화학", corp_code: "00356361" },
];

export default function App() {
  const [selectedStock, setSelectedStock] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [done, setDone] = useState(false);

  const handleAnalyze = async (stock) => {
    setSelectedStock(stock);
    setDone(false);
    setAnalyzing(true);

    try {
      await fetch(`http://localhost:8000/analyze/${stock.code}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stock_name: stock.name, corp_code: stock.corp_code }),
      });

      const poll = async () => {
        const res = await fetch(`http://localhost:8000/analyze/${stock.code}/status`);
        const data = await res.json();
        if (data.status === "done") {
          setAnalyzing(false);
          setDone(true);
        } else if (data.status.startsWith("error")) {
          setAnalyzing(false);
          alert("분석 중 오류: " + data.status);
        } else {
          setTimeout(poll, 2000);
        }
      };
      setTimeout(poll, 3000);
    } catch (e) {
      setAnalyzing(false);
      alert("서버 연결 실패. api.py 실행 중인지 확인하세요.");
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <span className="logo">📊 AI 애널리스트</span>
          <span className="badge">Beta</span>
        </div>
      </header>

      <main className="app-main">
        {!selectedStock && !analyzing && !done ? (
          <div className="landing">
            <h1 className="landing-title">AI가 분석하는<br />나만의 바이사이드 리포트</h1>
            <p className="landing-sub">종목을 선택하면 투자 thesis부터 이탈 조건, 행동 제안까지 자동으로 생성합니다.</p>
            <SearchBar stocks={STOCK_LIST} onAnalyze={handleAnalyze} />
          </div>
        ) : analyzing ? (
          <div className="loading-screen">
            <div className="spinner" />
            <p className="loading-text">{selectedStock?.name} 분석 중...</p>
            <p className="loading-sub">thesis 생성 → 조건 설정 → 모니터링 순서로 진행됩니다</p>
          </div>
        ) : (
          <AnalysisResult
            stock={selectedStock}
            onBack={() => { setSelectedStock(null); setDone(false); }}
          />
        )}
      </main>
    </div>
  );
}
