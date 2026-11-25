import { useCallback, useEffect, useState } from 'react';
import { CheckIcon, RetryIcon } from '../components/icons';
import { linkProps } from '../lib/router';
import { reviewPath } from '../mail/format';
import { skillApi, type AuthorStatus, type DocStatus, type DraftDetail, type DraftItem } from './api';
import { AuthorMissing, Chip, Dialog, DocStatusChip, ErrorBox } from './ui';
import { buttonDanger, buttonOutline, buttonPrimary, errorMessage, formatDate, inputClass } from './format';

// 백엔드 agent/skills.py 와 같은 상한
const POLL_MS = 10_000;

const FILTERS: { key: 'all' | DocStatus; label: string }[] = [
    { key: 'all', label: '전체' },
    { key: 'draft', label: '검토 대기' },
    { key: 'generating', label: '생성 중' },
    { key: 'error', label: '생성 실패' },
    { key: 'rejected', label: '반려됨' },
];

function draftTitle(d: { name: string | null; version: number | null; status: DocStatus }) {
    if (d.name) return `${d.name}${d.version ? ` v${d.version}` : ''}`;
    return d.status === 'generating' ? '이름 정하는 중' : '이름 없음';
}

export function ReviewTab({ docId, onSelect }: { docId: number | null; onSelect: (id: number | null, replace?: boolean) => void }) {
    const [items, setItems] = useState<DraftItem[] | null>(null);
    const [author, setAuthor] = useState<AuthorStatus | null>(null);
    const [loadError, setLoadError] = useState('');
    const [filter, setFilter] = useState<'all' | DocStatus>('all');

    const load = useCallback(async (quiet = false) => {
        if (!quiet) setLoadError('');
        try {
            const data = await skillApi.drafts();
            setItems(data.items);
            setAuthor(data.author);
            setLoadError('');
        } catch (e) {
            if (!quiet) setLoadError(errorMessage(e, '초안 목록을 불러오지 못했습니다.'));
        }
    }, []);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void load();
    }, [load]);

    // 생성 중인 초안이 있으면 목록을 주기적으로 다시 받는다
    const generating = items?.some((d) => d.status === 'generating') ?? false;
    useEffect(() => {
        if (!generating) return;
        const id = window.setInterval(() => void load(true), POLL_MS);
        return () => window.clearInterval(id);
    }, [generating, load]);

    // 고른 초안이 없으면 첫 검토 대기 초안을 연다
    useEffect(() => {
        if (docId != null || !items?.length) return;
        const first = items.find((d) => d.status === 'draft') ?? items[0];
        onSelect(first.doc_id, true);
    }, [docId, items, onSelect]);

    const shown = items?.filter((d) => filter === 'all' || d.status === filter) ?? [];

    return (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
            <aside className="md:w-[300px] lg:w-[320px] shrink-0 border-b md:border-b-0 md:border-r border-divide p-4 md:p-5 md:overflow-y-auto">
                <h1 className="text-[16px] font-bold">검토 대기</h1>
                <p className="mt-1 text-[12px] leading-5 text-muted">
                    문의 사례로 만든 SKILL 초안입니다. 승인하기 전에는 어떤 답변에도 쓰이지 않습니다.
                </p>
                {author && !author.available && <div className="mt-3"><AuthorMissing reason={author.reason} /></div>}
                <div role="group" aria-label="상태 필터" className="mt-4 flex flex-wrap gap-1">
                    {FILTERS.map((f) => {
                        const count = f.key === 'all' ? items?.length : items?.filter((d) => d.status === f.key).length;
                        return (
                            <button
                                key={f.key}
                                type="button"
                                aria-pressed={filter === f.key}
                                onClick={() => setFilter(f.key)}
                                className={`h-7 px-2.5 rounded-full text-[11.5px] font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-brand ${
                                    filter === f.key ? 'bg-ink text-white' : 'bg-chip text-muted hover:text-ink'
                                }`}
                            >
                                {f.label}{count ? ` ${count}` : ''}
                            </button>
                        );
                    })}
                </div>
                <nav aria-label="초안 목록" className="mt-3 flex flex-col gap-2">
                    {items === null && !loadError && <p className="text-[12px] text-muted px-1 py-2">불러오는 중…</p>}
                    {items !== null && shown.length === 0 && (
                        <p className="text-[12px] text-muted px-1 py-2">
                            {items.length === 0 ? '검토할 초안이 없습니다. 문의 유형 탭에서 초안을 만들 수 있습니다.' : '이 상태의 초안이 없습니다.'}
                        </p>
                    )}
                    {shown.map((d) => {
                        const active = d.doc_id === docId;
                        return (
                            <button
                                key={d.doc_id}
                                type="button"
                                aria-pressed={active}
                                onClick={() => onSelect(d.doc_id)}
                                className={`rounded-xl border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-brand ${active ? 'border-brand/25 bg-brand-tint' : 'border-transparent hover:bg-chip'}`}
                            >
                                <span className="flex items-center gap-2">
                                    <span className={`min-w-0 flex-1 truncate text-[13px] font-semibold ${d.name ? '' : 'text-muted'}`}>{draftTitle(d)}</span>
                                    <DocStatusChip status={d.status} />
                                </span>
                                <span className="mt-1 block truncate text-[11.5px] text-muted">
                                    {d.type?.label ?? '유형 없음'} · {formatDate(d.created_at)}
                                </span>
                                {d.check && (
                                    <span className="mt-1 block text-[11px]">
                                        {d.check.errors > 0
                                            ? <span className="font-semibold text-danger">검사 오류 {d.check.errors}</span>
                                            : <span className="font-semibold text-brand-hover">검사 통과</span>}
                                        {d.check.warnings > 0 && <span className="text-[#8a5d00]"> · 경고 {d.check.warnings}</span>}
                                    </span>
                                )}
                            </button>
                        );
                    })}
                </nav>
            </aside>

            <main className="flex-1 min-w-0 md:overflow-y-auto bg-surface px-4 py-6 sm:p-8 lg:p-10">
                <div className="mx-auto max-w-[920px]">
                    {loadError ? (
                        <ErrorBox message={loadError} onRetry={() => void load()} />
                    ) : docId == null ? (
                        <p className="text-[13px] text-muted">{items === null ? '불러오는 중…' : '왼쪽에서 초안을 고르세요.'}</p>
                    ) : (
                        <DraftPanel key={docId} docId={docId} authorAvailable={author?.available ?? false} onChanged={() => void load(true)} onSelect={onSelect} />
                    )}
                </div>
            </main>
        </div>
    );
}

function DraftPanel({
    docId, authorAvailable, onChanged, onSelect,
}: { docId: number; authorAvailable: boolean; onChanged: () => void; onSelect: (id: number | null) => void }) {
    const [doc, setDoc] = useState<DraftDetail | null>(null);
    const [loadError, setLoadError] = useState('');
    const [edit, setEdit] = useState({ description: '', body: '' });
    const [busy, setBusy] = useState<'save' | 'approve' | 'reject' | 'regen' | null>(null);
    const [dialog, setDialog] = useState<'approve' | 'reject' | null>(null);
    const [note, setNote] = useState('');
    const [reason, setReason] = useState('');
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');

    const apply = useCallback((d: DraftDetail) => {
        setDoc(d);
        setEdit({ description: d.description ?? '', body: d.body ?? '' });
    }, []);

    const load = useCallback(async () => {
        setLoadError('');
        try {
            apply(await skillApi.draft(docId));
        } catch (e) {
            setLoadError(errorMessage(e, '초안을 불러오지 못했습니다.'));
        }
    }, [docId, apply]);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void load();
    }, [load]);

    // 생성 중이면 다 만들어질 때까지 다시 받는다
    const isGenerating = doc?.status === 'generating';
    useEffect(() => {
        if (!isGenerating) return;
        const id = window.setInterval(() => void load(), POLL_MS);
        return () => window.clearInterval(id);
    }, [isGenerating, load]);

    if (loadError) return <ErrorBox message={loadError} onRetry={() => void load()} />;
    if (!doc) return <p className="text-[13px] text-muted">초안을 불러오는 중…</p>;

    const editable = doc.status === 'draft';
    const dirty = editable && (edit.description !== (doc.description ?? '') || edit.body !== (doc.body ?? ''));
    const hasErrors = Boolean(doc.check && doc.check.errors.length > 0);
    const canApprove = editable && !dirty && !hasErrors && !busy;

    async function run<T>(kind: NonNullable<typeof busy>, action: () => Promise<T>, done: (r: T) => void, fallback: string) {
        setBusy(kind);
        setNotice('');
        setError('');
        try {
            done(await action());
            onChanged();
        } catch (e) {
            setError(errorMessage(e, fallback));
        } finally {
            setBusy(null);
        }
    }

    const save = () => run('save', () => skillApi.saveDraft(doc.doc_id, edit), (d) => {
        apply(d);
        setNotice(d.check?.ok ? '저장했습니다. 검사를 통과했습니다.' : '저장했습니다. 검사 오류를 고쳐야 승인할 수 있습니다.');
    }, '저장하지 못했습니다.');

    const approve = () => run('approve', () => skillApi.approve(doc.doc_id, note.trim()), (d) => {
        apply(d);
        setDialog(null);
        setNote('');
        setNotice('승인했습니다. 이후 답변에서 모델이 이 SKILL을 골라 읽을 수 있습니다. (사용 중 SKILL 탭)');
    }, '승인하지 못했습니다.');

    const reject = () => run('reject', () => skillApi.reject(doc.doc_id, reason.trim()), (d) => {
        apply(d);
        setDialog(null);
        setReason('');
        setNotice('반려했습니다. 이 유형은 자동으로 다시 만들지 않습니다 (다시 생성은 직접 누릅니다).');
    }, '반려하지 못했습니다.');

    const regenerate = () => {
        if (!doc.type) return;
        if (dirty && !window.confirm('저장하지 않은 변경이 있습니다. 버리고 새 초안을 요청할까요?')) return;
        void run('regen', () => skillApi.requestDraft(doc.type!.type_id), (r) => {
            setNotice(r.already ? '이미 생성 대기 중인 초안이 있어 그 초안을 엽니다.' : r.message);
            onSelect(r.doc_id);
        }, '초안 생성을 요청하지 못했습니다.');
    };

    return (
        <>
            <div className="flex flex-wrap items-center gap-2">
                <h2 className={`text-[22px] font-bold tracking-tight break-all ${doc.name ? '' : 'text-muted'}`}>{draftTitle(doc)}</h2>
                <DocStatusChip status={doc.status} />
                {doc.origin === 'edited' && <Chip className="border border-line bg-white text-muted">수정됨</Chip>}
            </div>
            <p className="mt-2 text-[13px] leading-6 text-muted">
                유형 <b className="font-semibold text-ink">{doc.type?.label ?? '없음'}</b> · {formatDate(doc.created_at)} 생성
                {doc.model && <> · {doc.model}</>}
                {doc.base_version != null && <> · 사용 중인 v{doc.base_version}을 고치는 새 버전</>}
                {doc.reviewed_at && <> · {formatDate(doc.reviewed_at)} {doc.reviewed_by ?? ''} 처리</>}
            </p>

            {doc.status === 'generating' && (
                <div role="status" className="mt-5 flex items-center gap-3 rounded-xl border border-brand/20 bg-brand-tint px-4 py-3 text-[13px] text-brand-hover">
                    <span className="w-4 h-4 rounded-full border-2 border-brand-pale border-t-brand animate-spin shrink-0" aria-hidden="true" />
                    생성 중입니다. 분석 스레드가 처리할 메일이 없을 때 만듭니다 (30초 주기).
                    {!authorAvailable && ' 지금은 작성 SKILL이 없어 만들지 않습니다.'}
                </div>
            )}
            {doc.status === 'error' && doc.error && (
                <div role="alert" className="mt-5 rounded-xl border border-danger/20 bg-danger-surface px-4 py-3 text-[13px] leading-6 text-danger">
                    <b className="font-bold">생성 실패</b> — {doc.error}
                </div>
            )}
            {doc.status === 'rejected' && doc.review_note && (
                <div className="mt-5 rounded-xl border border-line bg-white px-4 py-3 text-[13px] leading-6">
                    <b className="font-bold">반려 사유</b> — {doc.review_note}
                </div>
            )}

            {doc.check && (
                <section aria-label="검사 결과" className="mt-5 rounded-2xl border border-divide bg-white px-5 py-4">
                    <h3 className="text-[13px] font-semibold">
                        서버 검사 {doc.check.ok ? <span className="text-brand-hover">통과</span> : <span className="text-danger">오류 {doc.check.errors.length}건</span>}
                    </h3>
                    {doc.check.errors.length > 0 && (
                        <ul className="mt-2 space-y-1 text-[12.5px] leading-5 text-danger list-disc pl-5">
                            {doc.check.errors.map((e) => <li key={e}>{e}</li>)}
                        </ul>
                    )}
                    {doc.check.warnings.length > 0 && (
                        <ul className="mt-2 space-y-1 text-[12.5px] leading-5 text-[#8a5d00] list-disc pl-5">
                            {doc.check.warnings.map((w) => <li key={w}>{w}</li>)}
                        </ul>
                    )}
                    {doc.check.ok && doc.check.warnings.length === 0 && <p className="mt-1 text-[12px] text-muted">오류·경고가 없습니다.</p>}
                </section>
            )}

            {doc.status !== 'generating' && (
                <section aria-label="SKILL 내용" className="mt-5 overflow-hidden rounded-2xl border border-divide bg-white">
                    <div className="border-b border-divide px-5 py-4">
                        <label htmlFor="skill-description" className="text-[13px] font-semibold">설명 <span className="font-normal text-muted">— 답변 모델은 이 설명만 보고 SKILL을 고릅니다</span></label>
                        <textarea
                            id="skill-description"
                            value={edit.description}
                            onChange={(e) => { setEdit((c) => ({ ...c, description: e.target.value })); setNotice(''); }}
                            readOnly={!editable}
                            rows={2}
                            className={`mt-2 resize-y leading-6 ${inputClass} ${editable ? '' : 'bg-surface'}`}
                        />
                    </div>
                    <div className="p-4 sm:p-5">
                        <label htmlFor="skill-body" className="text-[13px] font-semibold">본문</label>
                        <textarea
                            id="skill-body"
                            value={edit.body}
                            onChange={(e) => { setEdit((c) => ({ ...c, body: e.target.value })); setNotice(''); }}
                            readOnly={!editable}
                            spellCheck={false}
                            className={`mt-2 min-h-[320px] md:min-h-[380px] resize-y p-4 text-[13px] leading-7 ${inputClass} ${editable ? '' : 'bg-surface'}`}
                        />
                        <p className="mt-2 text-right text-[11px] tabular-nums text-muted">
                            {edit.body.length.toLocaleString('ko-KR')}자
                        </p>
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-divide px-5 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                            {(editable || doc.status === 'error') && (
                                <button type="button" onClick={() => setDialog('reject')} disabled={Boolean(busy)} className={buttonDanger}>반려</button>
                            )}
                            {doc.type && (
                                <button
                                    type="button"
                                    onClick={regenerate}
                                    disabled={!authorAvailable || Boolean(busy)}
                                    title={authorAvailable ? '같은 유형의 사례로 새 초안을 만듭니다' : '작성 SKILL(create-skill)가 없어 만들 수 없습니다'}
                                    className={buttonOutline}
                                >
                                    <RetryIcon />{busy === 'regen' ? '요청 중…' : '다시 생성'}
                                </button>
                            )}
                        </div>
                        {editable && (
                            <div className="flex flex-wrap items-center gap-2">
                                <button type="button" onClick={() => { setEdit({ description: doc.description ?? '', body: doc.body ?? '' }); setNotice(''); }} disabled={!dirty || Boolean(busy)} className={buttonOutline}>
                                    변경 취소
                                </button>
                                <button type="button" onClick={() => void save()} disabled={!dirty || Boolean(busy)} className={buttonOutline}>
                                    {busy === 'save' ? '저장 중…' : '저장'}
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setDialog('approve')}
                                    disabled={!canApprove}
                                    title={hasErrors ? '검사 오류가 있어 승인할 수 없습니다' : dirty ? '변경을 저장한 뒤 승인할 수 있습니다' : undefined}
                                    className={buttonPrimary}
                                >
                                    <CheckIcon />승인
                                </button>
                            </div>
                        )}
                    </div>
                    {editable && (
                        <p className="border-t border-divide bg-brand-tint px-5 py-2.5 text-[12px] text-brand-hover">
                            승인하면 이후 답변에서 모델이 이 SKILL을 골라 읽을 수 있습니다.
                            {hasErrors && <span className="text-danger"> 지금은 검사 오류가 있어 승인할 수 없습니다.</span>}
                        </p>
                    )}
                </section>
            )}

            <p role="status" className="mt-3 min-h-5 text-[12px] text-brand-hover">{notice}</p>
            {error && <p role="alert" className="mt-1 text-[12px] text-danger">{error}</p>}

            <section aria-label="재료 사례" className="mt-4 rounded-2xl border border-divide bg-white px-5 py-4">
                <h3 className="text-[13px] font-semibold">재료 사례 {doc.cases.length}건</h3>
                <p className="mt-1 text-[12px] text-muted">초안을 만들 때 읽힌 문의입니다. 제목을 누르면 메일 검토 화면에서 원문과 답변을 봅니다.</p>
                {doc.cases.length === 0 ? (
                    <p className="mt-2 text-[12.5px] text-muted">사례가 없습니다.</p>
                ) : (
                    <ul className="mt-3 divide-y divide-divide">
                        {doc.cases.map((c) => (
                            <li key={c.task_id} className="flex flex-wrap items-center gap-2 py-2 text-[12.5px]">
                                <a {...linkProps(reviewPath(c.task_id))} className="min-w-0 flex-1 truncate font-semibold text-ink hover:text-brand-hover hover:underline">
                                    {c.subject || '(제목 없음)'}
                                </a>
                                {c.sent
                                    ? <Chip className="bg-brand-pale text-brand-hover">발송됨</Chip>
                                    : <Chip className="bg-chip text-muted">검토되지 않은 초안</Chip>}
                                <span className="text-[11.5px] text-muted tabular-nums">{formatDate(c.received_at)}</span>
                            </li>
                        ))}
                    </ul>
                )}
            </section>

            {dialog === 'approve' && (
                <Dialog
                    title={`${draftTitle(doc)} 승인`}
                    confirmLabel="승인"
                    busy={busy === 'approve'}
                    onConfirm={() => void approve()}
                    onClose={() => setDialog(null)}
                >
                    <p>승인하면 이후 메일·웹 답변에서 모델이 이 SKILL을 골라 읽을 수 있습니다. 근거 검증·실행 한도·발송 승인은 SKILL 내용과 관계없이 그대로입니다.</p>
                    <label htmlFor="approve-note" className="mt-3 block text-[12px] font-semibold">메모 (선택)</label>
                    <input id="approve-note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} className={`mt-1 h-9 ${inputClass}`} />
                    <p className="mt-3 rounded-lg bg-chip px-3 py-2 text-[12px] leading-5 text-muted">
                        로그인 기능이 없어 승인자는 요청한 PC의 IP 주소로만 기록됩니다.
                    </p>
                </Dialog>
            )}
            {dialog === 'reject' && (
                <Dialog
                    title={`${draftTitle(doc)} 반려`}
                    confirmLabel="반려"
                    confirmClass={buttonDanger}
                    confirmDisabled={!reason.trim()}
                    busy={busy === 'reject'}
                    onConfirm={() => void reject()}
                    onClose={() => setDialog(null)}
                >
                    <label htmlFor="reject-reason" className="block text-[12px] font-semibold">반려 사유 (필수)</label>
                    <textarea id="reject-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={2000} className={`mt-1 resize-y ${inputClass}`} />
                    <p className="mt-2 text-[12px] text-muted">반려된 유형은 자동으로 다시 만들지 않습니다.</p>
                </Dialog>
            )}
        </>
    );
}
