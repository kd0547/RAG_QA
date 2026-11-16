import { useState } from 'react';
import { useGraphSchema } from './schemaContext';
import type { EntityTypeDefinition } from './schemaContext';
import { graphWrite } from './write';

/**
 * 개체 종류 관리 (지시서 GR2). 기본 종류를 포함해 이름·설명·색·추출 여부·식별자 규칙·사용·순서를 고친다.
 * 합치기는 이 종류의 개체를 모두 다른 종류로 옮기고 종류를 지운다. 개체가 있는 종류는 그냥 지울 수 없다.
 * 백엔드: POST/PATCH/DELETE /graph/entity-types, POST /graph/entity-types/{key}/merge
 */
const input = 'w-full rounded border border-line bg-white px-2 py-1.5 text-sm';
const button = 'rounded border border-line bg-white px-2.5 py-1 text-xs font-semibold hover:bg-chip disabled:opacity-50';
const primary = 'rounded border border-brand bg-brand px-2.5 py-1 text-xs font-semibold text-white hover:bg-brand-hover disabled:opacity-50';

interface Draft {
    key: string; label: string; description: string; color: string;
    extract: boolean; requires_identifier: boolean; sort_order: number;
}
const blank: Draft = { key: '', label: '', description: '', color: '#0E7490', extract: false, requires_identifier: false, sort_order: 0 };

function draftOf(t: EntityTypeDefinition): Draft {
    return { key: t.key, label: t.label, description: t.description, color: t.color, extract: !!t.extract,
        requires_identifier: !!t.requires_identifier, sort_order: t.sort_order };
}

export function EntityTypeManager({ onChanged }: { onChanged: () => void }) {
    const { schema, refresh } = useGraphSchema();
    const [editing, setEditing] = useState<string | null>(null); // 종류 key, 새 종류는 ''
    const [draft, setDraft] = useState<Draft>(blank);
    const [mergeFrom, setMergeFrom] = useState<string | null>(null);
    const [mergeInto, setMergeInto] = useState('');
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');

    const run = async (action: () => Promise<string | void>) => {
        setBusy(true); setError(''); setNotice('');
        try {
            const message = await action();
            if (message) setNotice(message);
            refresh(); onChanged();
        } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
        finally { setBusy(false); }
    };
    const current = (key: string) => schema.entity_types.find((t) => t.key === key);

    const save = () => run(async () => {
        if (editing === '') {
            await graphWrite('/entity-types', 'POST', { ...draft, sort_order: draft.sort_order || undefined });
        } else if (editing) {
            const before = current(editing);
            if (!before) return;
            const { key: _key, ...fields } = draft;
            void _key;
            await graphWrite(`/entity-types/${editing}`, 'PATCH', { ...fields, expected_revision: before.revision });
        }
        setEditing(null);
        return '저장했습니다.';
    });

    const toggleActive = (t: EntityTypeDefinition) => run(async () => {
        if (t.active && t.used_by_projection
            && !window.confirm(`사양 투영이 "${t.label}" 종류를 씁니다. 사용 중지하면 사양 DB를 그래프로 옮길 때 이 종류의 노드를 만들지 않습니다. 계속할까요?`)) return;
        await graphWrite(`/entity-types/${t.key}`, 'PATCH', { active: !t.active, expected_revision: t.revision });
        return t.active ? `"${t.label}" 사용을 멈췄습니다. 기존 개체는 그대로 보이고 검색됩니다.` : `"${t.label}"을(를) 다시 씁니다.`;
    });

    const remove = (t: EntityTypeDefinition) => run(async () => {
        if (!window.confirm(`"${t.label}" 종류를 지울까요?`)) return;
        await graphWrite(`/entity-types/${t.key}?expected_revision=${t.revision}`, 'DELETE');
        return '종류를 지웠습니다.';
    });

    const merge = () => run(async () => {
        const from = mergeFrom ? current(mergeFrom) : undefined;
        if (!from || !mergeInto) return;
        const into = current(mergeInto);
        if (!window.confirm(`"${from.label}"의 개체 ${from.entity_count}개를 "${into?.label ?? mergeInto}"(으)로 옮기고 "${from.label}" 종류를 지웁니다. 같은 이름의 개체는 하나로 합칩니다.`)) return;
        const result = await graphWrite<{ moved: number; merged: number }>(`/entity-types/${from.key}/merge`, 'POST',
            { into: mergeInto, expected_revision: from.revision });
        setMergeFrom(null); setMergeInto('');
        return `옮긴 개체 ${result.moved}개, 같은 이름이라 합친 개체 ${result.merged}개`;
    });

    const form = editing !== null && <form className="space-y-2 rounded border border-brand/30 bg-surface p-3" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <p className="text-xs font-bold">{editing === '' ? '새 종류' : `${current(editing)?.label ?? editing} 수정`}</p>
        {editing === '' && <label className="block text-xs">내부 키 (영문 소문자·숫자·_, 바꿀 수 없음)
            <input required pattern="[a-z][a-z0-9_]{1,29}" className={input} value={draft.key} onChange={(e) => setDraft({ ...draft, key: e.target.value })} /></label>}
        <label className="block text-xs">이름<input required maxLength={100} className={input} value={draft.label} onChange={(e) => setDraft({ ...draft, label: e.target.value })} /></label>
        <label className="block text-xs">설명 <span className="text-muted">· 문서 추출 때 이 설명이 그대로 쓰입니다</span>
            <textarea className={input} rows={3} maxLength={4000} value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} /></label>
        <div className="flex flex-wrap items-center gap-3 text-xs">
            <label className="flex items-center gap-1">색<input type="color" aria-label="종류 색" value={draft.color} onChange={(e) => setDraft({ ...draft, color: e.target.value })} /></label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={draft.extract} onChange={(e) => setDraft({ ...draft, extract: e.target.checked })} /> 문서 추출 대상</label>
            <label className="flex items-center gap-1"><input type="checkbox" checked={draft.requires_identifier} onChange={(e) => setDraft({ ...draft, requires_identifier: e.target.checked })} /> 이름에 식별자 필요 (추출만)</label>
            <label className="flex items-center gap-1">순서<input type="number" className="w-20 rounded border border-line px-1" value={draft.sort_order} onChange={(e) => setDraft({ ...draft, sort_order: Number(e.target.value) })} /></label>
        </div>
        <div className="flex gap-2"><button className={primary} disabled={busy}>저장</button>
            <button type="button" className={button} onClick={() => setEditing(null)}>취소</button></div>
    </form>;

    return <div className="space-y-3">
        <p className="text-xs text-muted">기본 종류도 모두 고칠 수 있습니다. 식별자 규칙·추출 여부는 문서 자동 추출만 거르고, 사람의 편집은 막지 않습니다.</p>
        <button className={button} onClick={() => { setEditing(''); setDraft(blank); }}>종류 추가</button>
        {form}
        <ul className="divide-y divide-line rounded border border-line">
            {schema.entity_types.map((t) => <li key={t.key} className="space-y-1 p-2 text-xs">
                <div className="flex flex-wrap items-center gap-2">
                    <span aria-hidden className="inline-block h-3 w-3 rounded-full" style={{ background: t.color }} />
                    <b className={t.active ? '' : 'text-muted line-through'}>{t.label}</b>
                    <span className="text-muted">{t.key} · 개체 {t.entity_count}{t.builtin ? ' · 기본' : ''}{t.extract ? ' · 추출' : ''}{t.requires_identifier ? ' · 식별자' : ''}{t.used_by_projection ? ' · 사양 투영' : ''}{t.active ? '' : ' · 사용 중지'}</span>
                </div>
                {t.description && <p className="text-muted">{t.description}</p>}
                <div className="flex flex-wrap gap-1.5">
                    <button className={button} disabled={busy} onClick={() => { setEditing(t.key); setDraft(draftOf(t)); }}>수정</button>
                    <button className={button} disabled={busy} onClick={() => void toggleActive(t)}>{t.active ? '사용 중지' : '다시 사용'}</button>
                    <button className={button} disabled={busy} onClick={() => { setMergeFrom(t.key); setMergeInto(''); }}>합치기</button>
                    <button className={button} disabled={busy || t.entity_count > 0} title={t.entity_count > 0 ? '개체가 있는 종류는 합치기로 옮기세요' : undefined}
                        onClick={() => void remove(t)}>삭제</button>
                </div>
                {mergeFrom === t.key && <div className="flex flex-wrap items-center gap-2 rounded bg-surface p-2">
                    <label className="flex items-center gap-1">합칠 종류
                        <select aria-label="합칠 종류" className="rounded border border-line px-1 py-0.5" value={mergeInto} onChange={(e) => setMergeInto(e.target.value)}>
                            <option value="">선택</option>
                            {schema.entity_types.filter((o) => o.key !== t.key).map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
                        </select></label>
                    <button className={primary} disabled={busy || !mergeInto} onClick={() => void merge()}>합치기 실행</button>
                    <button className={button} onClick={() => setMergeFrom(null)}>취소</button>
                </div>}
            </li>)}
        </ul>
        {notice && <p className="text-xs text-brand-hover">{notice}</p>}
        {error && <p role="alert" className="text-xs text-danger">{error}</p>}
    </div>;
}
