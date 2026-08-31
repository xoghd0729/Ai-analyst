"""
api/routers/auth.py — 간단 로그인 + 내 포트폴리오 저장/목록
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

캡스톤용 경량 사용자 인프라.
- 파일 기반 저장(data/users.json, data/saved_portfolios.json) — DB 불필요, 어디서나 동작
- 비밀번호는 salt + SHA-256 해시로 저장 (평문 저장 안 함)
- 토큰(secrets) 기반 단순 인증 — 로그인 시 발급, 헤더/바디로 검증

엔드포인트 (prefix=/api/auth, /api/portfolio 일부)
  POST /api/auth/register   {email, password} -> {token, email}
  POST /api/auth/login      {email, password} -> {token, email}
  POST /api/auth/save       {token, name, payload} -> {id}
  GET  /api/auth/my?token=  -> [{id, name, created_at, summary}]
  GET  /api/auth/saved/{id}?token= -> {full saved payload}
  DELETE /api/auth/saved/{id}?token= -> {ok}
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()

BASE_DIR     = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
USERS_PATH   = os.path.join(BASE_DIR, "data", "users.json")
TOKENS_PATH  = os.path.join(BASE_DIR, "data", "auth_tokens.json")
SAVED_PATH   = os.path.join(BASE_DIR, "data", "saved_portfolios.json")
_LOCK = threading.Lock()


def _load(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _hash_pw(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _email_of(token: str) -> str:
    tokens = _load(TOKENS_PATH, {})
    email = tokens.get(token)
    if not email:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다 (토큰 무효).")
    return email


# ── 요청 모델 ─────────────────────────────────────────────────
class AuthReq(BaseModel):
    email:    str
    password: str

class SaveReq(BaseModel):
    token:   str
    name:    str
    payload: dict          # recommend_portfolio 결과 + 입력값


# ── 회원가입 ──────────────────────────────────────────────────
@router.post("/register")
def register(req: AuthReq):
    email = req.email.strip().lower()
    if not email or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="이메일과 4자 이상 비밀번호가 필요합니다.")
    with _LOCK:
        users = _load(USERS_PATH, {})
        if email in users:
            raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다.")
        salt = secrets.token_hex(8)
        users[email] = {
            "salt":       salt,
            "pwd_hash":   _hash_pw(req.password, salt),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _save(USERS_PATH, users)
        token = secrets.token_hex(16)
        tokens = _load(TOKENS_PATH, {})
        tokens[token] = email
        _save(TOKENS_PATH, tokens)
    return {"token": token, "email": email}


# ── 로그인 ────────────────────────────────────────────────────
@router.post("/login")
def login(req: AuthReq):
    email = req.email.strip().lower()
    with _LOCK:
        users = _load(USERS_PATH, {})
        u = users.get(email)
        if not u or _hash_pw(req.password, u["salt"]) != u["pwd_hash"]:
            raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
        token = secrets.token_hex(16)
        tokens = _load(TOKENS_PATH, {})
        tokens[token] = email
        _save(TOKENS_PATH, tokens)
    return {"token": token, "email": email}


# ── 포트폴리오 저장 ───────────────────────────────────────────
@router.post("/save")
def save_portfolio(req: SaveReq):
    email = _email_of(req.token)
    with _LOCK:
        saved = _load(SAVED_PATH, {})
        pid = secrets.token_hex(8)
        # 목록용 요약 추출 (가벼운 스냅샷)
        p = req.payload or {}
        survival = p.get("survival", {})
        meta = p.get("_meta", {})
        summary = {
            "monthly_target": p.get("monthly_target") or p.get("input", {}).get("monthly_target"),
            "age":            p.get("age") or p.get("input", {}).get("age"),
            "health_score":   survival.get("health_score"),
            "survival":       survival.get("survival_probability"),
            "achieve_age":    meta.get("achieve_age"),
            "monthly_div":    meta.get("monthly_div"),
        }
        saved[pid] = {
            "id":         pid,
            "owner":      email,
            "name":       req.name or "내 포트폴리오",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary":    summary,
            "payload":    p,
        }
        _save(SAVED_PATH, saved)
    return {"id": pid}


# ── 내 포트폴리오 목록 ────────────────────────────────────────
@router.get("/my")
def my_portfolios(token: str):
    email = _email_of(token)
    saved = _load(SAVED_PATH, {})
    mine = [
        {"id": v["id"], "name": v["name"], "created_at": v["created_at"], "summary": v.get("summary", {})}
        for v in saved.values() if v.get("owner") == email
    ]
    mine.sort(key=lambda x: x["created_at"], reverse=True)
    return {"email": email, "portfolios": mine}


# ── 저장된 포트폴리오 1건 ─────────────────────────────────────
@router.get("/saved/{pid}")
def get_saved(pid: str, token: str):
    email = _email_of(token)
    saved = _load(SAVED_PATH, {})
    item = saved.get(pid)
    if not item or item.get("owner") != email:
        raise HTTPException(status_code=404, detail="포트폴리오를 찾을 수 없습니다.")
    return item


# ── 삭제 ──────────────────────────────────────────────────────
@router.delete("/saved/{pid}")
def delete_saved(pid: str, token: str):
    email = _email_of(token)
    with _LOCK:
        saved = _load(SAVED_PATH, {})
        item = saved.get(pid)
        if not item or item.get("owner") != email:
            raise HTTPException(status_code=404, detail="포트폴리오를 찾을 수 없습니다.")
        del saved[pid]
        _save(SAVED_PATH, saved)
    return {"ok": True}
