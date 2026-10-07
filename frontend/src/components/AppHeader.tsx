import type { ReactNode } from 'react';
import { linkProps } from '../lib/router';
import { LogoMark } from './icons';

type AppKey = 'rag' | 'mail';

/** 앱 전환 대상. (OCR 도구는 미구현이라 노출하지 않는다 — /ocr 경로는 그대로 남아 있다) */
const APPS: { key: AppKey; label: string; path: string }[] = [
    { key: 'rag', label: 'TG RAG', path: '/' },
    { key: 'mail', label: '메일', path: '/mail' },
];

/**
 * 모든 화면 공통 상단 바.
 * 왼쪽: 로고 + 앱 전환 스위치(TG RAG ⇄ 메일) · 가운데: 화면별 탭(children) · 오른쪽: 보조 영역(aside)
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
