"""
utils/merton_dtd.py
Merton Distance-to-Default (DtD) — 시장신호 기반 부도/배당삭감 위험 지표

원리:
  - 주가 = 기업 자산가치의 콜옵션 (Black-Scholes)
  - 자산가치(V) 와 자산변동성(sigma_V) 를 주가·변동성으로 역산
  - DtD = (V - D) / (V * sigma_V)   ← 숫자 클수록 안전
  - 낮은 DtD = 자산이 부채에 가까워짐 = 배당 삭감 선행지표

활용:
  - run_merton(ticker, period='2y') → DtD 시계열
  - add_merton_feature(df) → survival_model.py 피처에 추가
  - "재무제표가 못 본 위기를 시장이 먼저 본다" 검증 실험
"""

import numpy as np
import pandas as pd
from pathlib import Path
from scipy.stats import norm
from scipy.optimize import fsolve
import warnings
warnings.filterwarnings("ignore")

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False


# ─────────────────────────────────────────────────────────────
# 핵심 수식: Merton 연립방정식 풀기
# ─────────────────────────────────────────────────────────────
def _merton_equations(params, E, sigma_E, D, r, T=1.0):
    """
    V, sigma_V 를 구하는 연립방정식 (Black-Scholes 역산)
    params = [V, sigma_V]
    E      = 시가총액
    sigma_E = 주가 연변동성
    D      = 총부채 (book value)
    r      = 무위험 이자율
    T      = 만기 (1년)
    """
    V, sigma_V = params
    if V <= 0 or sigma_V <= 0:
        return [1e10, 1e10]

    d1 = (np.log(V / D) + (r + 0.5 * sigma_V**2) * T) / (sigma_V * np.sqrt(T))
    d2 = d1 - sigma_V * np.sqrt(T)

    # eq1: E = V*N(d1) - D*exp(-rT)*N(d2)
    eq1 = V * norm.cdf(d1) - D * np.exp(-r * T) * norm.cdf(d2) - E
    # eq2: sigma_E * E = V * N(d1) * sigma_V
    eq2 = sigma_E * E - V * norm.cdf(d1) * sigma_V

    return [eq1, eq2]


def calc_dtd(equity: float, sigma_equity: float, debt: float,
             r: float = 0.03, T: float = 1.0) -> float:
    """
    단일 시점 Distance-to-Default 계산

    Parameters
    ----------
    equity      : 시가총액 (원 단위)
    sigma_equity: 주가 연변동성 (0~1)
    debt        : 총부채 (원 단위)
    r           : 무위험이자율 (기본 3%)
    T           : 만기 (기본 1년)

    Returns
    -------
    dtd : float  (양수=안전, 음수=위험)
    """
    if debt <= 0 or equity <= 0 or sigma_equity <= 0:
        return np.nan

    V0 = equity + debt  # 초기값
    try:
        sol = fsolve(_merton_equations, [V0, sigma_equity],
                     args=(equity, sigma_equity, debt, r, T),
                     full_output=True)
        V, sigma_V = sol[0]
        if V <= 0 or sigma_V <= 0:
            return np.nan

        d2 = (np.log(V / debt) + (r - 0.5 * sigma_V**2) * T) / (sigma_V * np.sqrt(T))
        return float(d2)   # = DtD
    except Exception:
        return np.nan


# ─────────────────────────────────────────────────────────────
# yfinance 로 종목별 DtD 시계열 계산
# ─────────────────────────────────────────────────────────────
def run_merton(ticker: str, period: str = "2y", r: float = 0.03) -> pd.DataFrame:
    """
    yfinance 주가 데이터로 연간 DtD 계산

    Parameters
    ----------
    ticker : str  예) "005930.KS" (삼성전자), "SCHD" (미국 ETF)
    period : str  "2y" / "5y" / "10y"
    r      : float 무위험이자율

    Returns
    -------
    DataFrame with columns: date, close, sigma_annual, market_cap, dtd
    """
    if not YF_AVAILABLE:
        raise ImportError("pip3 install yfinance")

    stock = yf.Ticker(ticker)
    hist  = stock.history(period=period)
    if hist.empty:
        return pd.DataFrame()

    # 일간 수익률 → 연변동성 (252거래일 롤링 252일)
    hist["ret"]        = hist["Close"].pct_change()
    hist["sigma_ann"]  = hist["ret"].rolling(252).std() * np.sqrt(252)

    # 부채 (최근 연간 재무제표)
    try:
        bs = stock.balance_sheet
        if bs.empty:
            debt = np.nan
        else:
            debt_row = bs.loc["Total Debt"] if "Total Debt" in bs.index else bs.loc["Long Term Debt"]
            debt = float(debt_row.iloc[0])
    except Exception:
        debt = np.nan

    # 시가총액 근사 = 주가 × 발행주식수
    try:
        shares = stock.info.get("sharesOutstanding", None)
    except Exception:
        shares = None

    hist = hist.dropna(subset=["sigma_ann"])
    rows = []
    for date, row in hist.iterrows():
        if shares:
            mcap = row["Close"] * shares
        else:
            mcap = np.nan

        dtd = calc_dtd(mcap, row["sigma_ann"], debt, r=r) if (mcap and not np.isnan(debt)) else np.nan
        rows.append({"date": date, "close": row["Close"],
                     "sigma_annual": row["sigma_ann"], "market_cap": mcap, "dtd": dtd})

    return pd.DataFrame(rows).set_index("date")


CACHE_PATH = Path(__file__).parent.parent / "data" / "merton_cache.csv"


# ─────────────────────────────────────────────────────────────
# 생존분석 데이터셋에 Merton DtD 피처 추가
# ─────────────────────────────────────────────────────────────
def add_merton_feature(df: pd.DataFrame,
                       market_cap_col: str = "market_cap",
                       debt_col: str = "total_liab",
                       sigma_col: str = None) -> pd.DataFrame:
    """
    dividend_dataset.csv 에 merton_dtd 컬럼 추가.

    우선순위:
      1. data/merton_cache.csv 존재 → 캐시에서 merge (실주가 기반)
         build_merton_cache.py 로 생성: python3 utils/build_merton_cache.py

      2. 캐시 없음 → 재무제표 근사 (sigma=0.25 고정, equity=total_equity)
         ※ 정확도 낮음 — 캐시 빌드 권장

    옵션 B (yfinance 주가 있을 때):
      - run_merton() 결과를 연도별 merge

    Parameters
    ----------
    df             : dividend_dataset.csv 로드한 DataFrame
    market_cap_col : 시가총액 컬럼명 (없으면 total_equity 대체)
    debt_col       : 부채 컬럼명
    sigma_col      : 연변동성 컬럼명 (없으면 0.25 대체)
    """
    df = df.copy()

    # ── 캐시 우선 사용 ──────────────────────────────────────────
    if CACHE_PATH.exists():
        cache = pd.read_csv(CACHE_PATH)[["stock_code", "year", "merton_dtd", "sigma_annual"]]
        cache["stock_code"] = cache["stock_code"].astype(str)
        df["stock_code"]    = df["stock_code"].astype(str)
        df = df.drop(columns=["merton_dtd", "sigma_annual"], errors="ignore")
        df = df.merge(cache, on=["stock_code", "year"], how="left")
        coverage = df["merton_dtd"].notna().mean()
        print(f"  [Merton] 캐시 로드: {len(cache)}행, 커버리지 {coverage*100:.1f}%")
        return df

    # ── 캐시 없음 → 재무제표 근사 (정확도 낮음) ─────────────────
    print("  [Merton] 캐시 없음 — 재무제표 근사 사용 (sigma=0.25 고정)")
    print("           정확한 결과는: python3 utils/build_merton_cache.py")

    DEFAULT_SIGMA = 0.25   # 업종 평균 연변동성 대체값

    dtd_vals = []
    for _, row in df.iterrows():
        # 시가총액: market_cap > total_equity 순으로 폴백
        if market_cap_col in df.columns and pd.notna(row.get(market_cap_col)):
            equity = float(row[market_cap_col])
        elif "total_equity" in df.columns and pd.notna(row.get("total_equity")):
            equity = float(row["total_equity"])
        else:
            dtd_vals.append(np.nan)
            continue

        # 부채
        debt = float(row[debt_col]) if (debt_col in df.columns and pd.notna(row.get(debt_col))) else np.nan
        if np.isnan(debt):
            dtd_vals.append(np.nan)
            continue

        # 변동성
        sigma = float(row[sigma_col]) if (sigma_col and sigma_col in df.columns
                                          and pd.notna(row.get(sigma_col))) else DEFAULT_SIGMA

        dtd_vals.append(calc_dtd(equity, sigma, debt))

    df["merton_dtd"] = dtd_vals
    return df


# ─────────────────────────────────────────────────────────────
# 메인: Merton DtD 피처 추가 후 생존모델 성능 비교
# ─────────────────────────────────────────────────────────────
def run_merton_experiment():
    """
    dividend_dataset.csv 에 merton_dtd 추가 →
    7피처 vs 8피처(+merton_dtd) C-index 비교
    """
    from pathlib import Path
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import cross_val_score, StratifiedKFold

    DATA = Path(__file__).parent.parent / "data" / "dividend_dataset.csv"
    df = pd.read_csv(DATA)

    # Merton DtD 추가 (재무제표 기반 근사)
    df = add_merton_feature(df, debt_col="total_liab")

    FEATS_BASE  = ["payout_ratio", "dividend_coverage", "debt_ratio",
                   "fcf", "operating_cf", "revenue_yoy_pct", "interest_coverage"]
    FEATS_MERTON = FEATS_BASE + ["merton_dtd"]

    df[FEATS_MERTON] = df[FEATS_MERTON].fillna(df[FEATS_MERTON].median())
    for col in FEATS_MERTON:
        lo, hi = df[col].quantile(0.01), df[col].quantile(0.99)
        df[col] = df[col].clip(lo, hi)

    df = df[df["time_to_event"] >= 1]
    y = df["meaningful_cut"].values
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    results = {}
    for label, feats in [("7피처 (재무제표)", FEATS_BASE),
                          ("8피처 (+Merton DtD)", FEATS_MERTON)]:
        X = df[feats].values
        pipe = Pipeline([("sc", StandardScaler()),
                         ("clf", LogisticRegression(max_iter=1000,
                                                    class_weight="balanced", C=0.1))])
        auc = cross_val_score(pipe, X, y, cv=cv, scoring="roc_auc").mean()
        pipe.fit(X, y)
        proba = pipe.predict_proba(X)[:, 1]
        ci = roc_auc_score(y, proba)
        results[label] = {"cv_auc": auc, "c_index": ci}
        print(f"{label:<25}  CV AUC={auc:.3f}  C-index={ci:.3f}")

    delta = results["8피처 (+Merton DtD)"]["cv_auc"] - results["7피처 (재무제표)"]["cv_auc"]
    print(f"\nMerton DtD 추가 효과: {delta:+.3f}")
    if delta > 0.01:
        print("✅ 시장신호가 재무제표보다 추가 정보 제공 — Merton 피처 채택")
    elif delta > 0:
        print("⚠️  소폭 개선 — 실제 주가 변동성 데이터 추가 시 더 개선 예상")
    else:
        print("❌ 재무제표 근사 sigma=0.25 한계 — yfinance 실데이터 필요")

    return results


if __name__ == "__main__":
    print("=" * 55)
    print("Merton Distance-to-Default 실험")
    print("재무제표 단독 vs +Merton DtD C-index 비교")
    print("=" * 55)
    run_merton_experiment()
