import { useEffect, useRef, type ReactNode } from 'react';
import type { DocStatus } from './api';
import { buttonOutline, buttonPrimary, DOC_STATUS_META } from './format';

export function Chip({ className, children, title }: { className: string; children: ReactNode; title?: string }) {
    return (
        <span title={title} className={`inline-flex items-center h-[19px] px-2 rounded-full text-[11px] font-bold whitespace-nowrap ${className}`}>
            {children}
        </span>
    );
}

export function DocStatusChip({ status }: { status: DocStatus }) {
    const m = DOC_STATUS_META[status];
    return <Chip className={m.chip}>{m.label}</Chip>;
}

export function OriginBadge({ origin }: { origin: 'repo' | 'db' }) {
    return origin === 'repo'
        ? <Chip className="border border-line bg-white text-muted" title="저장소 skills/ 폴더의 절차 (git으로 관리, 화면에서 고칠 수 없음)">기본</Chip>
        : <Chip className="bg-brand-soft text-brand-hover" title="문의 사례로 만들어 R&D가 승인한 절차">생성</Chip>;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
    return (
        <div role="alert" className="rounded-xl border border-danger/20 bg-danger-surface px-4 py-3 text-[13px] text-danger flex flex-wrap items-center justify-between gap-2">
            <span>{message}</span>
            {onRetry && (
                <button
                    type="button"
                    onClick={onRetry}
                    className="h-8 rounded-lg border border-danger/30 bg-white px-3 text-[12px] font-semibold hover:bg-danger-soft focus-visible:outline-2 focus-visible:outline-danger"
                >
                    다시 시도
                </button>
            )}
        </div>
    );
}

/** 작성 절차(create-skill)가 없을 때의 안내. 초안 생성이 꺼져 있다. */
export function AuthorMissing({ reason }: { reason: string | null }) {
    return (
        <div role="note" className="rounded-xl border border-warn/30 bg-warn-soft/60 px-4 py-3 text-[12.5px] leading-5 text-[#6b4a00]">
            <b className="font-bold">작성 절차 없음</b> — 절차 초안 생성이 꺼져 있습니다. {reason}
            <br />설계자가 <code className="rounded bg-white/70 px-1">skills/create-skill/SKILL.md</code>(channels: author)를 넣고 서버를 다시 시작하면 켜집니다.
        </div>
    );
}

/** 확인 대화상자. 열리면 첫 입력(없으면 확인 버튼)에 초점을 둔다. Esc로 닫는다. */
export function Dialog({
    title,
    children,
    confirmLabel,
    confirmClass = buttonPrimary,
    confirmDisabled,
    busy,
    onConfirm,
    onClose,
}: {
    title: string;
    children: ReactNode;
    confirmLabel: string;
    confirmClass?: string;
    confirmDisabled?: boolean;
    busy?: boolean;
    onConfirm: () => void;
    onClose: () => void;
}) {
    const ref = useRef<HTMLDivElement>(null);
    const closeRef = useRef(onClose);
    useEffect(() => { closeRef.current = onClose; });
    useEffect(() => {
        // 열릴 때 한 번만 초점을 옮긴다 (입력할 때마다 옮기지 않게)
        const first = ref.current?.querySelector<HTMLElement>('textarea, input, select, [data-autofocus]');
        first?.focus();
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') closeRef.current(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);
    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
            <div ref={ref} role="dialog" aria-modal="true" aria-label={title} className="w-full max-w-[460px] rounded-2xl bg-white p-5 shadow-[0_12px_40px_rgba(20,28,43,0.18)]">
                <h3 className="text-[15px] font-bold">{title}</h3>
                <div className="mt-3 text-[13px] leading-6">{children}</div>
                <div className="mt-5 flex justify-end gap-2">
                    <button type="button" onClick={onClose} className={buttonOutline}>취소</button>
                    <button type="button" data-autofocus onClick={onConfirm} disabled={confirmDisabled || busy} className={confirmClass}>
                        {busy ? '처리 중…' : confirmLabel}
                    </button>
                </div>
            </div>
        </div>
    );
}
