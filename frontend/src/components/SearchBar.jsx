export default function SearchBar({ stocks, onAnalyze }) {
  return (
    <div className="stock-grid">
      {stocks.map((s) => (
        <button key={s.code} className="stock-card" onClick={() => onAnalyze(s)}>
          <div className="stock-card-name">{s.name}</div>
          <div className="stock-card-code">{s.code}</div>
        </button>
      ))}
    </div>
  );
}
