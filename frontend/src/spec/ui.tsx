/** 사양 관리 화면 공용 컴포넌트. 클래스 문자열과 유틸 함수는 styles.ts 에 있다 (fast refresh 규칙). */
import type { ReactNode } from 'react';

export function Field({ label, htmlFor, hint, children, className = '' }: { label: string; htmlFor?: string; hint?: string; children: ReactNode; className?: string }) {
    return (
        <div className={className}>
            <label htmlFor={htmlFor} className="block text-[12px] font-semibold text-ink">
                {label}
            </label>
            <div className="mt-1.5">{children}</div>
            {hint && <p className="mt-1 text-[11px] text-muted leading-relaxed">{hint}</p>}
        </div>
    );
}

export function Notice({ kind, children }: { kind: 'ok' | 'error'; children: ReactNode }) {
    const cls = kind === 'ok'
        ? 'border-brand/20 bg-brand-tint text-brand-hover'
        : 'border-danger/20 bg-danger-surface text-danger';
    return (
        <p role={kind === 'error' ? 'alert' : 'status'} className={`rounded-lg border px-3 py-2 text-[12.5px] leading-relaxed break-words ${cls}`}>
            {children}
        </p>
    );
}

export function Pill({ children, tone = 'muted' }: { children: ReactNode; tone?: 'muted' | 'brand' | 'warn' }) {
    const cls = tone === 'brand' ? 'bg-brand text-white' : tone === 'warn' ? 'bg-warn-soft text-warn' : 'border border-line bg-white text-muted';
    return <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap ${cls}`}>{children}</span>;
}

export function Card({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
    return (
        <section className="overflow-hidden rounded-2xl border border-divide bg-white">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-divide px-5 py-3.5">
                <h3 className="text-[14px] font-bold">{title}</h3>
                {aside}
            </div>
            <div className="px-5 py-4">{children}</div>
        </section>
    );
}

/** 왼쪽 목록의 항목 버튼 */
export function ListItem({ active, title, subtitle, badge, onClick }: { active: boolean; title: string; subtitle?: string; badge?: ReactNode; onClick: () => void }) {
    return (
        <button
            type="button"
            aria-pressed={active}
            onClick={onClick}
            className={`w-full flex items-center gap-3 rounded-xl border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-brand ${
                active ? 'border-brand/25 bg-brand-tint' : 'border-transparent hover:bg-chip'
            }`}
        >
            <span className="min-w-0 flex-1">
                <span className="block text-[13px] font-semibold truncate">{title}</span>
                {subtitle && <span className="block mt-0.5 text-[11px] text-muted truncate">{subtitle}</span>}
            </span>
            {badge}
        </button>
    );
}
