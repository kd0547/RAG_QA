import { useCallback, useEffect, useState } from 'react';
import { skillApi, type SkillDetail, type SkillItem, type SkillList } from './api';
import { AuthorMissing, Chip, Dialog, DocStatusChip, ErrorBox, OriginBadge } from './ui';
import { buttonDanger, buttonOutline, buttonPrimary, errorMessage, formatDate } from './format';

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
            setLoadError(errorMessage(e, 'SKILL 목록을 불러오지 못했습니다.'));
        }
    }, []);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void load();
    }, [load]);

    useEffect(() => {
        if (name == null && data?.items.length) onSelect(data.items[0].name, true);
    }, [name, data, onSelect]);

    const answerItems = data?.items.filter((s) => !s.author) ?? [];
    const authorItems = data?.items.filter((s) => s.author) ?? [];

    return (
        <div className="flex-1 min-h-0 flex flex-col md:flex-row">
            <aside className="md:w-[300px] lg:w-[320px] shrink-0 border-b md:border-b-0 md:border-r border-divide p-4 md:p-5 md:overflow-y-auto">
                <h1 className="text-[16px] font-bold">사용 중 SKILL</h1>
                <p className="mt-1 text-[12px] leading-5 text-muted">
                    <b className="font-semibold text-ink">저장소</b>는 skills/ 폴더의 SKILL 파일로, 넣거나 고치면 서버 재시작 없이 다음 실행부터 반영됩니다.
                    {' '}<b className="font-semibold text-ink">생성</b>은 R&D가 승인한 SKILL입니다.
                    {data && <> 사용 횟수는 최근 {data.settings.usage_days}일 동안 그 SKILL을 쓴 실행 수입니다.</>}
                </p>
                {data?.loaded_at && <p className="mt-1 text-[11.5px] text-muted">파일을 마지막으로 읽은 시각 {formatDate(data.loaded_at)}</p>}
                {data && !data.author.available && <div className="mt-3"><AuthorMissing author={data.author} /></div>}
                {data && data.load_errors.length > 0 && <LoadErrors errors={data.load_errors} />}
                {data === null && !loadError && <p className="mt-4 text-[12px] text-muted px-1 py-2">불러오는 중…</p>}
                {answerItems.length > 0 && <SkillNav label="답변 SKILL" items={answerItems} selected={name} onSelect={onSelect} />}
                {authorItems.length > 0 && <SkillNav label="작성 SKILL" items={authorItems} selected={name} onSelect={onSelect} />}
            </aside>

            <main className="flex-1 min-w-0 md:overflow-y-auto bg-surface px-4 py-6 sm:p-8 lg:p-10">
                <div className="mx-auto max-w-[920px]">
                    {loadError ? (
                        <ErrorBox message={loadError} onRetry={() => void load()} />
                    ) : name == null ? (
                        <p className="text-[13px] text-muted">{data === null ? '불러오는 중…' : '왼쪽에서 SKILL을 고르세요.'}</p>
                    ) : (
                        <SkillPanel key={name} name={name} uses={data?.items.find((s) => s.name === name)?.uses_30d}
                                    onChanged={() => void load()} onOpenDraft={onOpenDraft} />
                    )}
                </div>
            </main>
        </div>
    );
}

function SkillNav({
    label, items, selected, onSelect,
}: { label: string; items: SkillItem[]; selected: string | null; onSelect: (name: string) => void }) {
    return (
        <nav aria-label={label} className="mt-4">
            <h2 className="px-1 text-[11.5px] font-semibold text-muted">{label}</h2>
            <div className="mt-1.5 flex flex-col gap-2">
                {items.map((s) => {
                    const active = s.name === selected;
                    return (
                        <button
                            key={s.name}
                            type="button"
                            aria-pressed={active}
                            onClick={() => onSelect(s.name)}
                            className={`rounded-xl border p-3 text-left transition-colors focus-visible:outline-2 focus-visible:outline-brand ${active ? 'border-brand/25 bg-brand-tint' : 'border-transparent hover:bg-chip'}`}
                        >
                            <span className="flex items-center gap-2">
                                <span className={`min-w-0 flex-1 truncate text-[13px] font-semibold ${s.enabled ? '' : 'text-muted line-through decoration-muted/60'}`}>
                                    {s.name}{s.version ? ` v${s.version}` : ''}
                                </span>
                                {!s.enabled && <Chip className="bg-chip text-muted">꺼짐</Chip>}
                                <OriginBadge origin={s.origin} />
                            </span>
                            <span className="mt-1 flex flex-wrap items-center gap-x-2 text-[11.5px] text-muted">
                                <span>{s.author ? '초안 생성에 씀' : '모델이 골라 읽음'}</span>
                                {!s.author && <span className="tabular-nums">· 사용 {s.uses_30d}회</span>}
                                <span>· {s.channels.join('·')}</span>
                                {s.files.length > 0 && <span>· 참고 파일 {s.files.length}</span>}
                            </span>
                        </button>
                    );
                })}
            </div>
        </nav>
    );
}

/** skills/ 폴더에 있지만 검사를 통과하지 못해 쓰지 않는 문서. 고치면 다음 실행 때 다시 읽는다. */
function LoadErrors({ errors }: { errors: { folder: string; reason: string }[] }) {
    return (
        <details className="mt-3 rounded-xl border border-warn/30 bg-warn-soft/60 px-4 py-3 text-[12px] leading-5 text-[#6b4a00]">
            <summary className="cursor-pointer font-bold">불러오지 못한 문서 {errors.length}개</summary>
            <ul className="mt-2 space-y-1.5">
                {errors.map((e) => (
                    <li key={e.folder} className="break-words">
                        <code className="rounded bg-white/70 px-1">skills/{e.folder}</code> — {e.reason}
                    </li>
                ))}
            </ul>
            <p className="mt-2 text-[11.5px]">파일을 고치면 서버 재시작 없이 다음 실행 때 다시 읽습니다.</p>
        </details>
    );
}

function SkillPanel({
    name, uses, onChanged, onOpenDraft,
}: { name: string; uses?: number; onChanged: () => void; onOpenDraft: (docId: number) => void }) {
    const [skill, setSkill] = useState<SkillDetail | null>(null);
    const [loadError, setLoadError] = useState('');
    const [busy, setBusy] = useState<'edit' | 'retire' | 'toggle' | null>(null);
    const [confirm, setConfirm] = useState<'retire' | 'disable' | null>(null);
    const [notice, setNotice] = useState('');
    const [error, setError] = useState('');

    const load = useCallback(async () => {
        setLoadError('');
        try {
            setSkill(await skillApi.get(name));
        } catch (e) {
            setLoadError(errorMessage(e, 'SKILL을 불러오지 못했습니다.'));
        }
    }, [name]);

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        void load();
    }, [load]);

    if (loadError) return <ErrorBox message={loadError} onRetry={() => void load()} />;
    if (!skill) return <p className="text-[13px] text-muted">SKILL을 불러오는 중…</p>;

    const isRepo = skill.origin === 'repo';
    const enabled = skill.enabled !== false;

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
            setConfirm(null);
            setNotice('사용을 멈췄습니다. 이후 답변의 선택 SKILL 목록에서 빠집니다. 다시 쓰려면 "다시 쓰기"로 새 버전 초안을 만들어 승인하세요.');
            onChanged();
        } catch (e) {
            setError(errorMessage(e, '사용 중지하지 못했습니다.'));
        } finally {
            setBusy(null);
        }
    }

    async function toggle(on: boolean) {
        setBusy('toggle');
        setError('');
        try {
            setSkill(await (on ? skillApi.enable(name) : skillApi.disable(name)));
            setConfirm(null);
            setNotice(on
                ? '다시 켰습니다. 다음 실행부터 쓰입니다.'
                : '껐습니다. 다음 실행부터 쓰이지 않습니다. 파일은 그대로이고 언제든 다시 켤 수 있습니다.');
            onChanged();
        } catch (e) {
            setError(errorMessage(e, on ? '다시 켜지 못했습니다.' : '끄지 못했습니다.'));
        } finally {
            setBusy(null);
        }
    }

    return (
        <>
            <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[22px] font-bold tracking-tight break-all">{skill.name}{skill.version ? ` v${skill.version}` : ''}</h2>
                <OriginBadge origin={skill.origin} />
                {skill.author && <Chip className="border border-line bg-white text-muted">작성 SKILL</Chip>}
                {isRepo && !enabled && <Chip className="bg-chip text-muted">꺼짐</Chip>}
                {!isRepo && !skill.active && <Chip className="bg-chip text-muted">사용 중지</Chip>}
            </div>
            <p className="mt-2 text-[13px] leading-6 text-muted">
                {skill.description}
            </p>
            <p className="mt-1 text-[12px] text-muted">
                채널 {skill.channels.join('·')} · digest <code className="rounded bg-chip px-1 text-ink">{skill.digest}</code>
                {uses != null && !skill.author && <> · 최근 30일 {uses}회</>}
                {skill.type?.label && <> · 유형 {skill.type.label}</>}
            </p>

            {isRepo ? (
                <div className="mt-4 rounded-xl border border-line bg-white px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                        {enabled ? (
                            <button type="button" onClick={() => setConfirm('disable')} disabled={Boolean(busy)} className={buttonDanger}>끄기</button>
                        ) : (
                            <button type="button" onClick={() => void toggle(true)} disabled={Boolean(busy)} className={buttonPrimary}>
                                {busy === 'toggle' ? '켜는 중…' : '다시 켜기'}
                            </button>
                        )}
                        {!enabled && skill.disabled_at && (
                            <span className="text-[12px] text-muted">{formatDate(skill.disabled_at)}{skill.disabled_by ? ` · ${skill.disabled_by}` : ''}에 끔</span>
                        )}
                    </div>
                    <p className="mt-2 text-[12.5px] leading-5 text-muted">
                        본문은 <code className="rounded bg-chip px-1 text-ink">skills/{skill.name}/SKILL.md</code> 파일에서 고칩니다. 고치면 서버 재시작 없이 다음 실행부터 반영됩니다.
                        끄면 파일은 그대로 두고 답변{skill.author ? '·초안 생성' : ''}에서만 뺍니다.
                    </p>
                </div>
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
                        <button type="button" onClick={() => setConfirm('retire')} disabled={Boolean(busy)} className={buttonDanger}>사용 중지</button>
                    )}
                </div>
            )}
            <p role="status" className="mt-2 min-h-5 text-[12px] text-brand-hover">{notice}</p>
            {error && <p role="alert" className="mt-1 text-[12px] text-danger">{error}</p>}

            <section aria-label="본문" className={`mt-3 rounded-2xl border border-divide bg-white p-5 ${enabled ? '' : 'opacity-70'}`}>
                <h3 className="text-[13px] font-semibold">본문</h3>
                <pre className="mt-3 whitespace-pre-wrap break-words font-sans text-[13px] leading-7 text-ink">{skill.body}</pre>
            </section>

            {skill.files && skill.files.length > 0 && (
                <section aria-label="참고 파일" className="mt-4 rounded-2xl border border-divide bg-white px-5 py-4">
                    <h3 className="text-[13px] font-semibold">참고 파일</h3>
                    <p className="mt-1 text-[12px] text-muted">모델이 본문을 읽은 뒤 필요할 때 load_skill(name, file)로 읽습니다.</p>
                    <ul className="mt-2 space-y-1 text-[12.5px]">
                        {skill.files.map((f) => (
                            <li key={f}><code className="rounded bg-chip px-1 text-ink">skills/{skill.name}/{f}</code></li>
                        ))}
                    </ul>
                </section>
            )}

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

            {confirm === 'retire' && (
                <Dialog
                    title={`${skill.name} 사용 중지`}
                    confirmLabel="사용 중지"
                    confirmClass={buttonDanger}
                    busy={busy === 'retire'}
                    onConfirm={() => void retire()}
                    onClose={() => setConfirm(null)}
                >
                    <p>이후 답변의 선택 SKILL 목록에서 빠지고, 이 SKILL을 맡던 문의 유형의 연결도 끊깁니다. 버전 이력은 남습니다.</p>
                    <p className="mt-2 rounded-lg bg-chip px-3 py-2 text-[12px] leading-5 text-muted">로그인 기능이 없어 처리자는 요청한 PC의 IP 주소로만 기록됩니다.</p>
                </Dialog>
            )}
            {confirm === 'disable' && (
                <Dialog
                    title={`${skill.name} 끄기`}
                    confirmLabel="끄기"
                    confirmClass={buttonDanger}
                    busy={busy === 'toggle'}
                    onConfirm={() => void toggle(false)}
                    onClose={() => setConfirm(null)}
                >
                    {skill.author ? (
                        <p>SKILL 초안 생성이 멈춥니다. 다시 켜면 이어서 만듭니다.</p>
                    ) : (
                        <p>다음 실행부터 선택 SKILL 목록과 검색에서 빠지고, 이 SKILL을 맡던 문의 유형의 연결이 끊깁니다. 다시 켜도 유형 연결은 되살아나지 않습니다.</p>
                    )}
                    <p className="mt-2">파일은 지우지 않습니다. 언제든 다시 켤 수 있습니다.</p>
                    <p className="mt-2 rounded-lg bg-chip px-3 py-2 text-[12px] leading-5 text-muted">로그인 기능이 없어 처리자는 요청한 PC의 IP 주소로만 기록됩니다.</p>
                </Dialog>
            )}
        </>
    );
}
