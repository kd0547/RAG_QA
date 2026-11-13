import { useCallback, useEffect, useState } from 'react';
import { skillApi, type SkillDetail, type SkillList } from './api';
import { AuthorMissing, Chip, Dialog, DocStatusChip, ErrorBox, OriginBadge } from './ui';
import { buttonDanger, buttonOutline, errorMessage, formatDate } from './format';

export function ActiveTab({
    name, onSelect, onOpenDraft,
}: { name: string | null; onSelect: (name: string | null, replace?: boolean) => void; onOpenDraft: (docId: number) => void }) {
    const [data, setData] = useState<SkillList | null>(null);
    const [loadError, setLoadError] = useState('');

    const load = useCallback(async () => {
        setLoadError('');
        try {
            setData(await skillApi.list());
        } catch (e) {
            setLoadError(errorMessage(e, '절차 목록을 불러오지 못했습니다.'));
        }
    }, []);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void load();
    }, [load]);

    useEffect(() => {
        if (name == null && data?.items.length) onSelect(data.items[0].name, true);
    }, [name, data, onSelect]);

    return (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
            <aside className="md:w-[300px] lg:w-[320px] shrink-0 border-b md:border-b-0 md:border-r border-divide p-4 md:p-5 md:overflow-y-auto">
                <h1 className="text-[16px] font-bold">사용 중 절차</h1>
                <p className="mt-1 text-[12px] leading-5 text-muted">
                    <b className="font-semibold text-ink">기본</b>은 저장소(skills/) 절차, <b className="font-semibold text-ink">생성</b>은 R&D가 승인한 절차입니다.
                    {data && <> 사용 횟수는 최근 {data.settings.usage_days}일 동안 그 절차를 쓴 실행 수입니다.</>}
                </p>
                {data && !data.author.available && <div className="mt-3"><AuthorMissing reason={data.author.reason} /></div>}
                <nav aria-label="절차 목록" className="mt-4 flex flex-col gap-2">
                    {data === null && !loadError && <p className="text-[12px] text-muted px-1 py-2">불러오는 중…</p>}
                    {data?.items.map((s) => {
                        const active = s.name === name;
                        return (
                            <button
                                key={s.name}
                                type="button"
                                aria-pressed={active}
                                onClick={() => onSelect(s.name)}
                                className={`rounded-xl border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-brand ${active ? 'border-brand/25 bg-brand-tint' : 'border-transparent hover:bg-chip'}`}
                            >
                                <span className="flex items-center gap-2">
                                    <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">{s.name}{s.version ? ` v${s.version}` : ''}</span>
                                    <OriginBadge origin={s.origin} />
                                </span>
                                <span className="mt-1 flex flex-wrap items-center gap-x-2 text-[11.5px] text-muted">
                                    <span className={s.server_applied ? 'font-semibold text-ink' : ''}>{s.server_applied ? '서버가 항상 적용' : '모델이 골라 읽음'}</span>
                                    <span className="tabular-nums">· 사용 {s.uses_30d}회</span>
                                    <span>· {s.channels.join('·')}</span>
                                </span>
                            </button>
                        );
                    })}
                </nav>
            </aside>

            <main className="flex-1 min-w-0 md:overflow-y-auto bg-surface px-4 py-6 sm:p-8 lg:p-10">
                <div className="mx-auto max-w-[920px]">
                    {loadError ? (
                        <ErrorBox message={loadError} onRetry={() => void load()} />
                    ) : name == null ? (
                        <p className="text-[13px] text-muted">{data === null ? '불러오는 중…' : '왼쪽에서 절차를 고르세요.'}</p>
                    ) : (
                        <SkillPanel key={name} name={name} uses={data?.items.find((s) => s.name === name)?.uses_30d}
                                    onChanged={() => void load()} onOpenDraft={onOpenDraft} />
                    )}
                </div>
            </main>
        </div>
    );
}

function SkillPanel({
    name, uses, onChanged, onOpenDraft,
}: { name: string; uses?: number; onChanged: () => void; onOpenDraft: (docId: number) => void }) {
    const [skill, setSkill] = useState<SkillDetail | null>(null);
    const [loadError, setLoadError] = useState('');
    const [busy, setBusy] = useState<'edit' | 'retire' | null>(null);
    const [confirmRetire, setConfirmRetire] = useState(false);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');

    const load = useCallback(async () => {
        setLoadError('');
        try {
            setSkill(await skillApi.get(name));
        } catch (e) {
            setLoadError(errorMessage(e, '절차를 불러오지 못했습니다.'));
        }
    }, [name]);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void load();
    }, [load]);

    if (loadError) return <ErrorBox message={loadError} onRetry={() => void load()} />;
    if (!skill) return <p className="text-[13px] text-muted">절차를 불러오는 중…</p>;

    async function newVersion() {
        setBusy('edit');
        setError('');
        try {
            const draft = await skillApi.newVersion(name);
            onOpenDraft(draft.doc_id);
        } catch (e) {
            setError(errorMessage(e, '새 버전 초안을 만들지 못했습니다.'));
        } finally {
            setBusy(null);
        }
    }

    async function retire() {
        setBusy('retire');
        setError('');
        try {
            setSkill(await skillApi.retire(name));
            setConfirmRetire(false);
            setNotice('사용을 멈췄습니다. 이후 답변의 선택 절차 목록에서 빠집니다. 다시 쓰려면 "다시 쓰기"로 새 버전 초안을 만들어 승인하세요.');
            onChanged();
        } catch (e) {
            setError(errorMessage(e, '사용 중지하지 못했습니다.'));
        } finally {
            setBusy(null);
        }
    }

    return (
        <>
            <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[22px] font-bold tracking-tight break-all">{skill.name}{skill.version ? ` v${skill.version}` : ''}</h2>
                <OriginBadge origin={skill.origin} />
                {skill.server_applied && <Chip className="bg-ink text-white">서버 적용</Chip>}
                {!skill.active && <Chip className="bg-chip text-muted">사용 중지</Chip>}
            </div>
            <p className="mt-2 text-[13px] leading-6 text-muted">
                {skill.description}
            </p>
            <p className="mt-1 text-[12px] text-muted">
                채널 {skill.channels.join('·')} · digest <code className="rounded bg-chip px-1 text-ink">{skill.digest}</code>
                {uses != null && <> · 최근 30일 {uses}회</>}
                {skill.type?.label && <> · 유형 {skill.type.label}</>}
            </p>

            {skill.read_only ? (
                <p className="mt-4 rounded-xl border border-line bg-white px-4 py-3 text-[12.5px] leading-5 text-muted">
                    저장소 절차는 화면에서 고치거나 멈출 수 없습니다. <code className="rounded bg-chip px-1 text-ink">skills/{skill.name}/SKILL.md</code>를 고치고 git으로 검토한 뒤 서버를 다시 시작합니다.
                </p>
            ) : (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                    {skill.open_draft ? (
                        <button type="button" onClick={() => onOpenDraft(skill.open_draft!.doc_id)} className={buttonOutline}>
                            검토 중인 v{skill.open_draft.version} 초안 열기
                        </button>
                    ) : (
                        <button type="button" onClick={() => void newVersion()} disabled={Boolean(busy)} className={buttonOutline}>
                            {busy === 'edit' ? '만드는 중…' : skill.active ? '고치기 (새 버전 초안)' : '다시 쓰기 (새 버전 초안)'}
                        </button>
                    )}
                    {skill.active && (
                        <button type="button" onClick={() => setConfirmRetire(true)} disabled={Boolean(busy)} className={buttonDanger}>사용 중지</button>
                    )}
                </div>
            )}
            <p role="status" className="mt-2 min-h-5 text-[12px] text-brand-hover">{notice}</p>
            {error && <p role="alert" className="mt-1 text-[12px] text-danger">{error}</p>}

            <section aria-label="본문" className="mt-3 rounded-2xl border border-divide bg-white p-5">
                <h3 className="text-[13px] font-semibold">본문</h3>
                <pre className="mt-3 whitespace-pre-wrap break-words font-sans text-[13px] leading-7 text-ink">{skill.body}</pre>
            </section>

            {skill.history.length > 0 && (
                <section aria-label="버전 이력" className="mt-4 rounded-2xl border border-divide bg-white px-5 py-4">
                    <h3 className="text-[13px] font-semibold">버전 이력</h3>
                    <ul className="mt-2 divide-y divide-divide">
                        {skill.history.map((h) => (
                            <li key={h.doc_id} className="flex flex-wrap items-center gap-2 py-2 text-[12.5px]">
                                <span className="w-10 font-semibold tabular-nums">v{h.version}</span>
                                <DocStatusChip status={h.status} />
                                {h.origin === 'edited' && <span className="text-[11.5px] text-muted">수정</span>}
                                <span className="text-[11.5px] text-muted">{formatDate(h.reviewed_at ?? h.created_at)}{h.reviewed_by ? ` · ${h.reviewed_by}` : ''}</span>
                                {h.review_note && <span className="min-w-0 flex-1 truncate text-[11.5px] text-muted">“{h.review_note}”</span>}
                                {(h.status === 'draft' || h.status === 'rejected') && (
                                    <button type="button" onClick={() => onOpenDraft(h.doc_id)} className="ml-auto text-[12px] font-semibold text-brand-hover hover:underline">열기</button>
                                )}
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {confirmRetire && (
                <Dialog
                    title={`${skill.name} 사용 중지`}
                    confirmLabel="사용 중지"
                    confirmClass={buttonDanger}
                    busy={busy === 'retire'}
                    onConfirm={() => void retire()}
                    onClose={() => setConfirmRetire(false)}
                >
                    <p>이후 답변의 선택 절차 목록에서 빠지고, 이 절차를 맡던 문의 유형의 연결도 끊깁니다. 버전 이력은 남습니다.</p>
                    <p className="mt-2 rounded-lg bg-chip px-3 py-2 text-[12px] leading-5 text-muted">로그인 기능이 없어 처리자는 요청한 PC의 IP 주소로만 기록됩니다.</p>
                </Dialog>
            )}
        </>
    );
}
