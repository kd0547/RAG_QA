import { useSyncExternalStore } from 'react'
import App from './App.tsx'
import { MailApprovalDashboard } from './mail/MailApprovalDashboard.tsx'

/** 라이브러리 없이 해시 기반 라우팅: #/mail 이면 승인 대시보드, 그 외엔 OCR 도구 */
function subscribe(cb: () => void) {
  window.addEventListener('hashchange', cb)
  return () => window.removeEventListener('hashchange', cb)
}
function getRoute() {
  return window.location.hash.replace(/^#\/?/, '')
}

export function Root() {
  const route = useSyncExternalStore(subscribe, getRoute)
  if (route === 'mail') return <MailApprovalDashboard />
  return <App />
}
