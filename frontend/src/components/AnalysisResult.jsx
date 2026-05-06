import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";

const BASE = "http://localhost:8000";

function getActionClass(rec) {
  if (rec === "부분매도") return "partial";
  if (rec === "매도") return "sell";
  return "hold";
}

function formatDate(str) {
  if (!str) return "";
  return new Date(str).toLocaleString("ko-KR", {
    month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export default function AnalysisResult({ stock, onBack }) {
  const [thesis, setThesis] = useState(null);
  const [conditions, setConditions] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [action, setAction] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAll = async () => {
      setLoading(true);
      try {
        const [t, c, al, ac] = await Promise.all([
          fetch(`${BASE}/thesis/${stock.code}`).then((r) => r.json()),
          fetch(`${BASE}/conditions/${stock.code}`).then((r) => r.json()),
          fetch(`${BASE}/alerts/${stock.code}`).then((r) => r.json()),
          fetch(`${BASE}/action/${stock.code}`).then((r) => r.json()),
        ]);
        setThesis(t);
        setConditions(c.conditions || []);
        setAlerts(al.alerts || []);
        setAction(ac);
      } catch (e) {
        console.error(e);
      }
      setLoading(false);
    };
    fetchAll();
  }, [stock.code]);

  if (loading) {
    return (
      <div style={{ textAlign: "center", paddingTop: 60 }}>
        <div className="spinner" />
        <p>결과 불러오는 중...</p>
      </div>
    );
  }

  const actionClass = getActionClass(action?.recommendation);
  const actionLabel = action?.recommendation || "유지";

  return (
    <div>
      <button className="back-btn" onClick={onBack}>← 종목 선택으로</button>
      <div className="stock-title">{stock.name}</div>
      <div className="stock-code">{stock.code}</div>

      {/* 행동 제안 */}
      <div className="section">
        <div className="section-label">행동 제안</div>
        <div className="card">
          <div className={`action-badge ${actionClass}`}>
            <span className={`action-dot ${actionClass}`} />
            {actionLabel}
          </div>
          <div className="action-detail">
            <ReactMarkdown>{action?.content || "이탈 조건 없음 — 현재 포지션 유지"}</ReactMarkdown>
          </div>
          {action?.created_at && (
            <div className="action-meta">생성 시각 {formatDate(action.created_at)}</div>
          )}
        </div>
      </div>

      {/* 투자 Thesis */}
      <div className="section">
        <div className="section-label">투자 Thesis</div>
        <div className="card">
          <div className="thesis-text">
            <ReactMarkdown>{thesis?.content || "데이터 없음"}</ReactMarkdown>
          </div>
          {thesis?.created_at && (
            <p style={{ fontSize: 12, color: "#8b95a1", marginTop: 12 }}>
              생성 {formatDate(thesis.created_at)}
            </p>
          )}
        </div>
      </div>

      {/* 이탈 조건 */}
      <div className="section">
        <div className="section-label">이탈 조건 ({conditions.length}개)</div>
        <div className="card">
          {conditions.length === 0 ? (
            <p className="no-data">조건 없음</p>
          ) : (
            conditions.map((c) => (
              <div className="condition-item" key={c.id}>
                <span className={`cond-type ${c.type || "threshold"}`}>
                  {c.type || "threshold"}
                </span>
                <span className="cond-desc">{c.description}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* 이탈 알림 */}
      <div className="section">
        <div className="section-label">
          이탈 알림
          {alerts.length > 0 && (
            <span style={{ marginLeft: 6, background: "#f03e3e", color: "#fff", fontSize: 11, fontWeight: 700, padding: "1px 7px", borderRadius: 100 }}>
              {alerts.length}
            </span>
          )}
        </div>
        <div className="card">
          {alerts.length === 0 ? (
            <p className="no-data">이탈 알림 없음 — 모든 조건 정상</p>
          ) : (
            alerts.map((a) => (
              <div className="alert-item" key={a.alert_id}>
                <span className="alert-dot" />
                <div className="alert-content">
                  <div className="alert-desc">{a.condition_description}</div>
                  <div className="alert-time">{formatDate(a.triggered_at)}</div>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
