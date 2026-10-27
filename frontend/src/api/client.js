import axios from 'axios'

// 배포 시 Vercel 환경변수 VITE_API_URL 에 백엔드 주소를 넣는다. (로컬은 기본값 사용)
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 120000,   // 무료 호스팅 콜드스타트(최대 ~60초) 대비
})

// 사이트 접속 즉시 서버를 깨워둔다 (무료 호스팅 콜드스타트 완화)
api.get('/api/health').catch(() => {})

// 무료 서버가 잠들어 있으면 깨어날 때까지 대기 (깨어 있으면 즉시 통과)
export async function wakeServer(onTick, maxMs = 240000) {
  const t0 = Date.now()
  while (Date.now() - t0 < maxMs) {
    try { await api.get('/api/health', { timeout: 8000 }); return true }
    catch { if (onTick) onTick(Math.round((Date.now() - t0) / 1000)); await new Promise(r => setTimeout(r, 2000)) }
  }
  return false
}

export default api
