import { useState } from 'react';
import { ApiError } from '../../lib/http';
import { btnDanger, btnGhost, btnPrimary, errorMessage, inputCls, selectCls, smallInputCls } from '../../spec/styles';
import { Field, Notice } from '../../spec/ui';
import { splitAliases, termApi, type TargetType, type Term, type TermInput, type TermKind, type TermTargets } from './api';

function emptyInput(): TermInput {
    return { name: '', aliases: [], target_type: '', target_key: '', description: '', members: [] };
}

function targetValue(type: TargetType, key: string): string {
    return type ? `${type}:${key}` : '';
}

/**
 * 용어 하나 직접 추가·수정. term이 null이면 새 용어. 부모는 key={term?.id ?? 'new'}로 그린다.
 * 종류: 용어(같은 뜻의 다른 표기) / 묶음(이름 하나가 여러 용어를 합쳐 부름, 구성 용어를 고른다).
 * 묶음 안에 묶음은 넣지 않는다: 구성 용어 후보는 일반 용어만, 다른 묶음의 구성 용어는 묶음이 될 수 없다.
 */
export function TermEditor({ term, terms, targets, onSaved, onDeleted, onCancel }: {
    term: Term | null;
    /** 구성 용어 후보를 고를 전체 용어 목록 */
    terms: Term[];
    targets: TermTargets | null;
    onSaved: (term: Term) => void;
    onDeleted: () => void;
    onCancel: () => void;
}) {
    // 다른 용어를 고르면 부모가 key를 바꿔 새로 그린다 (입력 중이던 값이 남지 않게)
    const [input, setInput] = useState<TermInput>(() => term
        ? {
            name: term.name, aliases: term.aliases, target_type: term.target_type, target_key: term.target_key,
            description: term.description, members: term.members.map((m) => m.id),
        }
        : emptyInput());
    const [kind, setKind] = useState<TermKind>(() => term?.kind ?? 'term');
    const [aliasText, setAliasText] = useState(() => (term ? term.aliases.join(', ') : ''));
    const [memberFilter, setMemberFilter] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [confirmDelete, setConfirmDelete] = useState(false);

    const parentBundles = term?.bundles ?? [];
    const candidates = terms.filter((t) => t.kind === 'term' && t.id !== term?.id);
    const shownCandidates = candidates.filter((t) => {
        const q = memberFilter.trim().toLowerCase();
        return !q || input.members.includes(t.id) || [t.name, ...t.aliases].some((v) => v.toLowerCase().includes(q));
    });

    async function save() {
        setSaving(true);
        setError('');
        const body: TermInput = kind === 'bundle'
            ? { ...input, aliases: splitAliases(aliasText), target_type: '', target_key: '' }  // 묶음은 연결 대상을 쓰지 않는다
            : { ...input, aliases: splitAliases(aliasText), members: [] };
        try {
            onSaved(term ? await termApi.update(term.id, body) : await termApi.create(body));
        } catch (e) {
            setError(errorMessage(e, '저장하지 못했습니다.'));
        } finally {
            setSaving(false);
        }
    }

    async function remove() {
        if (!term) return;
        setSaving(true);
        try {
            await termApi.remove(term.id);
            onDeleted();
        } catch (e) {
            setError(e instanceof ApiError ? e.message : '삭제하지 못했습니다.');
            setSaving(false);
        }
    }

    function toggleMember(id: number) {
        setInput({ ...input, members: input.members.includes(id) ? input.members.filter((m) => m !== id) : [...input.members, id] });
    }

    const aliases = splitAliases(aliasText);
    const memberNames = input.members.map((id) => terms.find((t) => t.id === id)?.name).filter(Boolean);
    const bundleInvalid = kind === 'bundle' && input.members.length === 0;

    return (
        <form
            className="max-w-2xl space-y-4"
            onSubmit={(e) => { e.preventDefault(); void save(); }}
        >
            <div>
                <h2 className="text-[15px] font-bold">{term ? '용어 수정' : '용어 직접 추가'}</h2>
                <p className="mt-1 text-[12px] text-muted">질문에 다른 표기가 나오면 그래프 검색이 표준 이름과 모든 표기로 개체를 찾습니다. 그래프에는 쓰지 않습니다.</p>
            </div>

            <Field label="종류">
                <div role="radiogroup" aria-label="종류" className="grid gap-2 sm:grid-cols-2">
                    {([
                        ['term', '용어', '같은 뜻의 다른 표기를 묶습니다. 예: 적합성 등록 = 전자파 인증'],
                        ['bundle', '묶음', '이름 하나가 여러 용어를 합쳐 부릅니다. 예: KC 인증 자료 = 적합성 등록 + 안전확인 신고'],
                    ] as const).map(([value, label, hint]) => {
                        const disabled = value === 'bundle' && parentBundles.length > 0;
                        return (
                            <label key={value} className={`flex gap-2 rounded-lg border px-3 py-2 text-[12px] leading-relaxed ${
                                kind === value ? 'border-brand/40 bg-brand-tint' : 'border-line'} ${disabled ? 'opacity-50' : 'cursor-pointer'}`}>
                                <input type="radio" name="term-kind" aria-label={label} className="mt-0.5" checked={kind === value} disabled={disabled}
                                    onChange={() => setKind(value)} />
                                <span><span className="block font-semibold text-ink">{label}</span><span className="text-muted">{hint}</span></span>
                            </label>
                        );
                    })}
                </div>
                {parentBundles.length > 0 && (
                    <p className="mt-1 text-[11px] text-muted">묶음 {parentBundles.map((b) => b.name).join(', ')}의 구성 용어라 묶음이 될 수 없습니다 (묶음 안에 묶음은 넣지 않습니다).</p>
                )}
            </Field>

            <Field label="표준 이름" htmlFor="term-name" hint={kind === 'bundle' ? '묶음 이름. 예: KC 인증 자료' : 'R&D에서 쓰는 이름. 예: 적합성 등록'}>
                <input id="term-name" className={inputCls} value={input.name} autoFocus={!term}
                    onChange={(e) => setInput({ ...input, name: e.target.value })} />
            </Field>

            <Field label="다른 표기" htmlFor="term-aliases" hint={kind === 'bundle'
                ? '묶음을 부르는 다른 말. 쉼표나 줄바꿈으로 나눕니다. 예: KC 인증, KC 서류'
                : '마케팅·입찰서 표현, 사내 약어, 영문. 쉼표나 줄바꿈으로 나눕니다. 예: 전자파 인증, KC 전파'}>
                <textarea id="term-aliases" rows={3} className={`${inputCls} h-auto py-2 leading-relaxed`} value={aliasText}
                    onChange={(e) => setAliasText(e.target.value)} />
                {aliases.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                        {aliases.map((a) => <span key={a} className="rounded-full border border-line bg-chip px-2 py-0.5 text-[11.5px]">{a}</span>)}
                    </div>
                )}
            </Field>

            {kind === 'bundle' && (
                <Field label={`구성 용어 (${input.members.length})`} hint="질문에 묶음 이름이 나오면 그래프 검색이 구성 용어마다 그 표기로 개체를 찾습니다. 일반 용어만 고를 수 있습니다.">
                    {memberNames.length > 0 && <p className="mb-2 text-[12px]"><span className="font-semibold">고른 용어:</span> {memberNames.join(' + ')}</p>}
                    {candidates.length === 0 ? (
                        <p className="text-[12px] text-muted">고를 용어가 없습니다. 구성할 용어(예: 적합성 등록, 안전확인 신고)를 먼저 추가하세요.</p>
                    ) : (
                        <div className="rounded-lg border border-line">
                            <div className="border-b border-divide p-2">
                                <input className={smallInputCls} placeholder="용어 찾기" aria-label="구성 용어 찾기" value={memberFilter}
                                    onChange={(e) => setMemberFilter(e.target.value)} />
                            </div>
                            <ul className="max-h-56 overflow-y-auto p-1">
                                {shownCandidates.map((t) => (
                                    <li key={t.id}>
                                        <label className="flex cursor-pointer items-start gap-2 rounded-md px-2 py-1.5 text-[12.5px] hover:bg-chip">
                                            <input type="checkbox" className="mt-0.5" checked={input.members.includes(t.id)} onChange={() => toggleMember(t.id)} />
                                            <span className="min-w-0">
                                                <span className="font-semibold">{t.name}</span>
                                                {t.aliases.length > 0 && <span className="ml-1.5 text-[11px] text-muted">{t.aliases.join(', ')}</span>}
                                            </span>
                                        </label>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                </Field>
            )}

            {kind === 'term' && (
                <Field label="연결 대상" htmlFor="term-target" hint="그래프 개체 종류를 고르면 그 종류의 개체만 찾습니다. 사양 속성을 고르면 모델이 사양 값을 읽을 때 씁니다.">
                    <select
                        id="term-target"
                        className={selectCls}
                        value={targetValue(input.target_type, input.target_key)}
                        onChange={(e) => {
                            const [type, ...rest] = e.target.value.split(':');
                            setInput({ ...input, target_type: (type || '') as TargetType, target_key: rest.join(':') });
                        }}
                    >
                        <option value="">없음</option>
                        {targets && targets.entity_type.length > 0 && (
                            <optgroup label="그래프 개체 종류">
                                {targets.entity_type.map((t) => <option key={t.key} value={`entity_type:${t.key}`}>{t.label}</option>)}
                            </optgroup>
                        )}
                        {targets && targets.spec_attribute.length > 0 && (
                            <optgroup label="사양 속성">
                                {targets.spec_attribute.map((t) => <option key={t.key} value={`spec_attribute:${t.key}`}>{t.label} ({t.key})</option>)}
                            </optgroup>
                        )}
                    </select>
                </Field>
            )}

            <Field label="설명" htmlFor="term-description" hint="정의, 답변할 때 주의할 점. 모델에게는 참고 자료로만 갑니다 (근거·지시가 아님).">
                <textarea id="term-description" rows={4} className={`${inputCls} h-auto py-2 leading-relaxed`} value={input.description}
                    onChange={(e) => setInput({ ...input, description: e.target.value })} />
            </Field>

            {term && term.kind === 'term' && parentBundles.length > 0 && (
                <p className="text-[12px] text-muted">들어 있는 묶음: {parentBundles.map((b) => b.name).join(', ')}</p>
            )}

            {error && <Notice kind="error">{error}</Notice>}

            <div className="flex flex-wrap items-center gap-2">
                <button type="submit" className={btnPrimary} disabled={saving || !input.name.trim() || bundleInvalid}>{term ? '저장' : '추가'}</button>
                <button type="button" className={btnGhost} onClick={onCancel} disabled={saving}>취소</button>
                {bundleInvalid && <span className="text-[12px] text-warn">구성 용어를 하나 이상 고르세요.</span>}
                {term && (
                    confirmDelete ? (
                        <span className="ml-auto flex items-center gap-2 text-[12px]">
                            <span className="text-danger">{term.kind === 'bundle' ? '묶음을 지웁니다 (구성 용어는 남습니다).' : '이 용어와 표기를 모두 지웁니다.'}</span>
                            <button type="button" className={btnDanger} onClick={() => void remove()} disabled={saving}>삭제</button>
                            <button type="button" className={btnGhost} onClick={() => setConfirmDelete(false)}>그만두기</button>
                        </span>
                    ) : (
                        <button type="button" className={`${btnDanger} ml-auto`} onClick={() => setConfirmDelete(true)} disabled={saving}>삭제</button>
                    )
                )}
            </div>
        </form>
    );
}
