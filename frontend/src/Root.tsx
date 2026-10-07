import { Suspense, lazy, useSyncExternalStore } from 'react'
import { MailApprovalDashboard } from './mail/MailApprovalDashboard.tsx'
import { RagConsole } from './rag/RagConsole.tsx'
import { getRoute, normalizeLegacyHash, subscribeRoute } from './lib/router'

/**
 * OCR 화면은 MDXEditor(→ @lexical/code → prismjs)를 끌고 온다.
 * prismjs 코어는 평가될 때 `window.Prism`을 세팅하고 `prism-clike.js` 같은 언어 파일은
 * 그 전역을 그대로 참조하는데, 번들러가 코어를 lazy CJS 래퍼로 감싸면 초기화가 밀려
 * `Prism is not defined`로 메인 청크가 통째로 죽는다.
 * → 별도 청크로 떼고, 에디터를 불러오기 전에 prism 코어를 먼저 평가해 전역을 세운다.
 */
const OcrTool = lazy(async () => {
  const prism = await import('prismjs')
  const g = globalThis as typeof globalThis & { Prism?: unknown }
  g.Prism ??= prism.default
  return import('./App.tsx')
})

normalizeLegacyHash() // 최초 로드 시 1회

function LoadingScreen() {
  return (
    <div className="h-screen w-full bg-white flex items-center justify-center">
      <div className="w-[46px] h-[46px] rounded-full border-[5px] border-brand-pale border-t-brand animate-spin" />
    </div>
  )
}

export function Root() {
  const route = useSyncExternalStore(subscribeRoute, getRoute)
  if (route === 'mail') return <MailApprovalDashboard />
  if (route === 'ocr') {
    return (
      <Suspense fallback={<LoadingScreen />}>
        <OcrTool />
      </Suspense>
    )
  }
  return <RagConsole />
}
