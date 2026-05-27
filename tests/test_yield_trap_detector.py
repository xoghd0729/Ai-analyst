import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.yield_trap_detector import detect_yield_traps


def test_high_yield_declining_price_detected():
    recs = [
        {
            "ticker": "TEST1",
            "name": "고배당하락주",
            "dividend_yield": 9.1,
            "price_cagr_3y": -7.0,
            "ml_status": "INTACT",
            "dividend_coverage": 1.2,
        }
    ]
    traps = detect_yield_traps(recs)
    assert len(traps) == 1
    assert traps[0]["ticker"] == "TEST1"
    assert "최근 3년 주가 CAGR" in traps[0]["reason"]


def test_broken_ml_class_detected():
    recs = [
        {
            "ticker": "TEST2",
            "name": "ML위험주",
            "dividend_yield": 4.2,
            "price_cagr_3y": 2.0,
            "ml_status": "BROKEN",
            "dividend_coverage": 1.1,
        }
    ]
    traps = detect_yield_traps(recs)
    assert len(traps) == 1
    assert "BROKEN" in traps[0]["reason"]


def test_low_dividend_coverage_detected():
    recs = [
        {
            "ticker": "TEST3",
            "name": "커버리지취약",
            "dividend_yield": 5.0,
            "price_cagr_3y": 0.0,
            "ml_status": "INTACT",
            "dividend_coverage": 0.7,
        }
    ]
    traps = detect_yield_traps(recs)
    assert len(traps) == 1
    assert "배당커버리지" in traps[0]["reason"]


def test_safe_stock_not_flagged():
    recs = [
        {
            "ticker": "SAFE1",
            "name": "안전주",
            "dividend_yield": 4.0,
            "price_cagr_3y": 6.0,
            "ml_status": "INTACT",
            "dividend_coverage": 1.5,
        }
    ]
    traps = detect_yield_traps(recs)
    assert traps == []


def test_returns_alternative_suggestions():
    recs = [
        {
            "ticker": "QYLD",
            "name": "QYLD",
            "dividend_yield": 11.0,
            "price_cagr_3y": -8.0,
            "ml_status": "INTACT",
            "dividend_coverage": 0.9,
        },
        {"ticker": "SCHD", "name": "SCHD"},
        {"ticker": "VYM", "name": "VYM"},
    ]
    traps = detect_yield_traps(recs)
    assert len(traps) == 1
    assert traps[0]["alternative_tickers"]
    assert "SCHD" in traps[0]["alternative_tickers"]
