// 간단 인증 + 포트폴리오 저장 헬퍼 (토큰은 localStorage)
import api from './client'

const TOKEN_KEY = 'cashflow_token'
const EMAIL_KEY = 'cashflow_email'

export function getToken()  { return localStorage.getItem(TOKEN_KEY) || '' }
export function getEmail()  { return localStorage.getItem(EMAIL_KEY) || '' }
export function isLoggedIn(){ return !!getToken() }

function setSession(token, email) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(EMAIL_KEY, email)
}

export function logout() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(EMAIL_KEY)
}

export async function register(email, password) {
  const { data } = await api.post('/api/auth/register', { email, password })
  setSession(data.token, data.email)
  return data
}

export async function login(email, password) {
  const { data } = await api.post('/api/auth/login', { email, password })
  setSession(data.token, data.email)
  return data
}

export async function savePortfolio(name, payload) {
  const { data } = await api.post('/api/auth/save', { token: getToken(), name, payload })
  return data
}

export async function myPortfolios() {
  const { data } = await api.get('/api/auth/my', { params: { token: getToken() } })
  return data.portfolios || []
}

export async function getSaved(id) {
  const { data } = await api.get(`/api/auth/saved/${id}`, { params: { token: getToken() } })
  return data
}

export async function deleteSaved(id) {
  const { data } = await api.delete(`/api/auth/saved/${id}`, { params: { token: getToken() } })
  return data
}
