import { useEffect, useRef, type ReactNode } from 'react';
import type { AuthorStatus, DocStatus } from './api';
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
        ? <Chip className="border border-line bg-white text-muted" title="skills/ 폴더의 SKILL 파일. 파일을 고치면 서버 재시작 없이 다음 실행부터 반영됩니다">저장소</Chip>
        : <Chip className="bg-brand-soft text-brand-hover" title="문의 사례로 만들어 R&D가 승인한 SKILL">생성</Chip>;
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

/** SKILL 초안 생성이 꺼져 있을 때의 안내: 설정으로 끈 경우(검증 전)와 작성 SKILL(create-skill)이 없는 경우. */
export function AuthorMissing({ author }: { author: AuthorStatus }) {
    if (author.disabled) {
        return (
            <div role="note" className="rounded-xl border border-line bg-chip px-4 py-3 text-[12.5px] leading-5 text-muted">
                <b className="font-bold text-ink">문의 유형 분류·SKILL 초안 생성 꺼짐</b> — LLM이 문의 유형을 나누고 SKILL 초안을 만드는 기능은 검증 전이라 꺼 두었습니다.
                이미 만들어진 유형·초안은 볼 수 있지만 새로 만들지 않습니다.
                <br />켜려면 <code className="rounded bg-white/70 px-1">.env</code>에 <code className="rounded bg-white/70 px-1">REQUEST_ANALYSIS_ENABLED=1</code>,{' '}
                <code className="rounded bg-white/70 px-1">SKILL_DRAFT_ENABLED=1</code>을 넣고 서버를 다시 시작합니다.
            </div>
        );
    }
    return (
        <div role="note" className="rounded-xl border border-warn/30 bg-warn-soft/60 px-4 py-3 text-[12.5px] leading-5 text-[#6b4a00]">
            <b className="font-bold">작성 SKILL 없음</b> — SKILL 초안 생성이 꺼져 있습니다. {author.reason}
            <br /><code className="rounded bg-white/70 px-1">skills/create-skill/SKILL.md</code>(channels: author)를 넣거나 사용 중 SKILL 화면에서 다시 켜면, 서버 재시작 없이 다음 요청부터 켜집니다.
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
