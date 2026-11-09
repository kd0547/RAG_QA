import type { ReactNode } from 'react';
import { linkProps } from '../lib/router';
import { LogoMark } from './icons';

type AppKey = 'rag' | 'mail' | 'spec' | 'knowledge' | 'prompt';

/**
 * 공통 메뉴. OCR 도구는 /ocr 경로로만 제공한다.
 * 제품 사양(/spec)은 그룹 문서 RAG 성능을 먼저 확인하는 동안 메뉴와 경로에서 숨긴다 (Root.tsx도 같이).
 * 다시 열려면 HIDDEN_APPS에서 'spec'을 빼고 Root.tsx의 spec 경로 주석을 풀면 된다.
 */
const HIDDEN_APPS: ReadonlySet<AppKey> = new Set<AppKey>(['spec']);
const ALL_APPS: { key: AppKey; label: string; path: string }[] = [
    { key: 'rag', label: 'TG RAG', path: '/' },
    { key: 'mail', label: '메일', path: '/mail' },
    { key: 'spec', label: '제품 사양', path: '/spec' },
    { key: 'knowledge', label: '지식 그래프', path: '/knowledge' },
    { key: 'prompt', label: '프롬프트', path: '/prompt' },
];
const APPS = ALL_APPS.filter((a) => !HIDDEN_APPS.has(a.key));

/**
 * 모든 화면 공통 상단 바.
 * 왼쪽: 로고 + 앱 전환 메뉴 · 가운데: 화면별 탭(children) · 오른쪽: 보조 영역(aside)
 */
export function AppHeader({
    current,
    children,
    aside,
}: {
    current: AppKey;
    children?: ReactNode;
    aside?: ReactNode;
}) {
    return (
        <header className="h-14 shrink-0 border-b border-divide px-3 sm:px-5 flex items-center gap-3 sm:gap-4">
            <LogoMark className="hidden sm:block w-5 h-5 shrink-0" />
            <div role="group" aria-label="앱 전환" className="shrink-0 flex p-0.5 rounded-full bg-chip">
                {APPS.map((a) => {
                    const active = a.key === current;
                    return (
                        <a
                            key={a.key}
                            {...linkProps(a.path)}
                            aria-current={active ? 'page' : undefined}
                            className={`h-7 px-3.5 inline-flex items-center rounded-full text-[12.5px] font-bold whitespace-nowrap transition-colors ${
                                active ? 'bg-ink text-white shadow-[0_1px_2px_rgba(20,28,43,0.2)]' : 'text-muted hover:text-ink'
                            }`}
                        >
                            {a.label}
                        </a>
                    );
                })}
            </div>
            {children && <span className="hidden sm:block w-px h-5 bg-divide shrink-0" aria-hidden />}
            {children}
            {aside && <div className="ml-auto flex items-center gap-2 shrink-0">{aside}</div>}
        </header>
    );
}
