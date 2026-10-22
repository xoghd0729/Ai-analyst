#!/bin/zsh
# AI Cashflow OS 서버 시작 스크립트
cd ~/ai-analyst

echo "=== API 서버 시작 ==="
osascript -e 'tell application "Terminal" to do script "cd ~/ai-analyst && source venv/bin/activate 2>/dev/null || true && uvicorn api.main:app --reload --port 8000"'

sleep 2

echo "=== 프론트엔드 시작 ==="
osascript -e 'tell application "Terminal" to do script "cd ~/ai-analyst/frontend && npm run dev"'

sleep 3

echo "=== 브라우저 열기 ==="
open http://localhost:5173

echo "완료! 브라우저에서 확인하세요."
