import axios from 'axios'

// 배포 시 Vercel 환경변수 VITE_API_URL 에 백엔드 주소를 넣는다. (로컬은 기본값 사용)
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 120000,   // 무료 호스팅 콜드스타트(최대 ~60초) 대비
})

export default api
