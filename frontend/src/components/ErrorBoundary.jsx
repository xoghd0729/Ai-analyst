import { Component } from 'react'

/**
 * ErrorBoundary — 발표 안전망
 *
 * React 컴포넌트 트리 어딘가에서 렌더링 예외가 발생해도
 * 화면 전체가 검정/빈 채로 멈추지 않게 해주는 컴포넌트.
 *
 * 사용:
 *   <ErrorBoundary>
 *     <Portfolio />
 *   </ErrorBoundary>
 *
 * 발표 도중 데이터 형태 변경 같은 사고가 나도 친절한 카드 + 새로고침 버튼이 뜸.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false, error: null, errorInfo: null }
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error }
  }

  componentDidCatch(error, errorInfo) {
    // 콘솔에 디버깅용 로그 남김 (사용자엔 안 보임)
    console.error('[ErrorBoundary] 캐치됨:', error)
    console.error('[ErrorBoundary] componentStack:', errorInfo?.componentStack)
    this.setState({ errorInfo })
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null })
  }

  handleReload = () => {
    window.location.reload()
  }

  render() {
    if (!this.state.hasError) return this.props.children

    const fallback = this.props.fallback
    if (fallback) return fallback(this.state.error, this.handleReset)

    return (
      <div style={{
        maxWidth: 720, margin: '40px auto', padding: '32px 28px',
        background: '#1a1230', borderRadius: 16,
        border: '1px solid #4c1d95', color: '#283143',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Pretendard", sans-serif',
      }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>⚠️</div>
        <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 8 }}>
          화면을 표시하는 중 문제가 발생했습니다
        </div>
        <div style={{ fontSize: 13, color: '#a5b4fc', marginBottom: 16, lineHeight: 1.6 }}>
          일시적인 데이터 처리 오류일 수 있습니다.
          아래 버튼으로 다시 시도해주세요.
        </div>

        {this.state.error && (
          <details style={{
            background: '#fef2f2', padding: '12px 14px', borderRadius: 8,
            border: '1px solid #312e81', marginBottom: 16,
            fontSize: 12, color: '#94a3b8',
          }}>
            <summary style={{ cursor: 'pointer', color: '#c4b5fd', fontWeight: 600 }}>
              기술적 상세 (개발자용)
            </summary>
            <pre style={{
              marginTop: 8, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
              fontFamily: 'monospace', fontSize: 11,
            }}>
              {String(this.state.error?.message || this.state.error)}
            </pre>
          </details>
        )}

        <div style={{ display: 'flex', gap: 10 }}>
          <button
            onClick={this.handleReset}
            style={{
              padding: '10px 18px', background: '#4f46e5',
              color: 'white', border: 'none', borderRadius: 8,
              fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            다시 시도
          </button>
          <button
            onClick={this.handleReload}
            style={{
              padding: '10px 18px', background: 'transparent',
              color: '#a5b4fc', border: '1px solid #4c1d95', borderRadius: 8,
              fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}
          >
            페이지 새로고침
          </button>
        </div>
      </div>
    )
  }
}
