import { useState } from 'react';

import { ApiError } from '../lib/http';
import { TypeChoices } from './GraphEditing';
import { useGraphSchema } from './schemaContext';
import type { PropertyDefinition, RelationDefinition } from './schemaContext';
import { graphWrite } from './write';

/**
 * 관계 종류·속성 정의 수정 (지시서 GR5). 기본 관계 종류도 이름·설명·허용 출발·도착 종류·추출 여부·활성을 고친다.
 * 허용 종류는 문서 자동 추출만 거른다. 사람이 넣는 관계는 규칙과 달라도 만들어지고 경고만 보인다.
 * 속성 정의의 자료형을 바꿀 때 기존 값이 새 자료형으로 읽히지 않으면 서버가 저장하지 않고 그 값 목록을 준다.
 */
const input = 'w-full rounded border border-line bg-white px-2 py-1 text-xs';
const button = 'rounded border border-line bg-white px-2.5 py-1 text-xs font-semibold hover:bg-chip disabled:opacity-50';

function RelationTypeForm({ definition, done }: { definition: RelationDefinition; done: () => void }) {
    const [label, setLabel] = useState(definition.label);
    const [description, setDescription] = useState(definition.description);
    const [sources, setSources] = useState(definition.source_entity_types);
    const [targets, setTargets] = useState(definition.target_entity_types);
    const [extract, setExtract] = useState(!!definition.extract);
    const [allowSelf, setAllowSelf] = useState(!!definition.allow_self);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const save = async () => {
        setBusy(true); setError('');
        try {
            await graphWrite(`/relation-types/${encodeURIComponent(definition.key)}`, 'PATCH', {
                label, description, source_entity_types: sources, target_entity_types: targets, extract, allow_self: allowSelf,
                expected_revision: definition.revision,
            });
            done();
        } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
    };
    return (
        <div className="mt-1 space-y-2 rounded border border-brand/30 bg-surface p-2">
            <label className="block">이름<input className={input} value={label} maxLength={100} onChange={(e) => setLabel(e.target.value)} /></label>
            <label className="block">설명 <span className="text-muted">· 문서 추출 때 이 설명이 쓰입니다</span>
                <textarea className={input} rows={2} value={description} maxLength={4000} onChange={(e) => setDescription(e.target.value)} /></label>
            <TypeChoices label="출발 객체 종류 →" values={sources} change={setSources} />
            <TypeChoices label="→ 도착 객체 종류" values={targets} change={setTargets} />
            <div className="flex flex-wrap gap-3">
                <label><input type="checkbox" checked={extract} onChange={(e) => setExtract(e.target.checked)} /> 문서 추출 대상</label>
                <label><input type="checkbox" checked={allowSelf} onChange={(e) => setAllowSelf(e.target.checked)} /> 자기 연결 허용</label>
            </div>
            <div className="flex gap-2"><button type="button" className={`${button} bg-brand text-white`} disabled={busy || !label.trim() || !sources.length || !targets.length} onClick={() => void save()}>저장</button>
                <button type="button" className={button} onClick={done}>취소</button></div>
            {error && <p role="alert" className="text-danger">{error}</p>}
        </div>
    );
}

function PropertyDefinitionForm({ definition, done }: { definition: PropertyDefinition; done: () => void }) {
    const [label, setLabel] = useState(definition.label);
    const [valueType, setValueType] = useState(definition.value_type);
    const [unit, setUnit] = useState(definition.unit ?? '');
    const [choices, setChoices] = useState(definition.allowed_values.join(', '));
    const [error, setError] = useState('');
    const [badValues, setBadValues] = useState<{ value_id: number; entity_id: number; value: unknown }[]>([]);
    const [busy, setBusy] = useState(false);
    const save = async () => {
        setBusy(true); setError(''); setBadValues([]);
        try {
            await graphWrite(`/property-definitions/${definition.property_id}`, 'PATCH', {
                label, value_type: valueType, unit: valueType === 'number' ? unit || null : null,
                allowed_values: valueType === 'enum' ? choices.split(',').map((s) => s.trim()).filter(Boolean) : [],
                expected_revision: definition.revision,
            });
            done();
        } catch (e) {
            const detail = e instanceof ApiError ? (e.detail as { values?: typeof badValues } | undefined) : undefined;
            if (detail?.values) setBadValues(detail.values);
            setError(e instanceof Error ? e.message : String(e));
        } finally { setBusy(false); }
    };
    return (
        <div className="mt-1 space-y-2 rounded border border-brand/30 bg-surface p-2">
            <label className="block">이름<input className={input} value={label} maxLength={100} onChange={(e) => setLabel(e.target.value)} /></label>
            <label className="block">자료형<select className={input} value={valueType} onChange={(e) => setValueType(e.target.value as PropertyDefinition['value_type'])}>
                {['text', 'number', 'boolean', 'date', 'enum'].map((v) => <option key={v}>{v}</option>)}</select></label>
            {valueType === 'number' && <label className="block">단위<input className={input} value={unit} onChange={(e) => setUnit(e.target.value)} /></label>}
            {valueType === 'enum' && <label className="block">선택지 (쉼표로 구분)<input className={input} value={choices} onChange={(e) => setChoices(e.target.value)} /></label>}
            <div className="flex gap-2"><button type="button" className={`${button} bg-brand text-white`} disabled={busy || !label.trim()} onClick={() => void save()}>저장</button>
                <button type="button" className={button} onClick={done}>취소</button></div>
            {error && <p role="alert" className="text-danger">{error}</p>}
            {badValues.length > 0 && <ul className="list-disc pl-4 text-danger">
                {badValues.map((v) => <li key={v.value_id}>객체 #{v.entity_id}: {String(v.value)}</li>)}
            </ul>}
        </div>
    );
}

export function DefinitionList({ mode, onChanged }: { mode: 'relation' | 'property'; onChanged: () => void }) {
    const { schema, refresh } = useGraphSchema();
    const [editing, setEditing] = useState<string | number | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const done = () => { setEditing(null); refresh(); onChanged(); };
    const toggle = async (path: string, active: boolean, revision: number) => {
        setBusy(true); setError('');
        try { await graphWrite(path, 'PATCH', { active: !active, expected_revision: revision }); refresh(); onChanged(); }
        catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
    };
    return (
        <div className="space-y-2 border-t border-line pt-3 text-xs">
            <p className="font-bold">등록된 정의 · 기본 정의도 고칠 수 있습니다 · 비활성화해도 기존 값은 보존</p>
            {mode === 'relation' ? schema.relation_types.map((d) => (
                <div key={d.key}>
                    <div className="flex items-center justify-between gap-2">
                        <span>{d.label} · {d.key}{d.builtin ? ' · 기본' : ''}{d.extract ? ' · 추출' : ''} · rev {d.revision}</span>
                        <span className="flex shrink-0 gap-1">
                            <button type="button" className={button} disabled={busy} onClick={() => setEditing(d.key)}>수정</button>
                            <button type="button" className={button} disabled={busy} onClick={() => void toggle(`/relation-types/${encodeURIComponent(d.key)}`, !!d.active, d.revision)}>{d.active ? '비활성화' : '활성화'}</button>
                        </span>
                    </div>
                    {editing === d.key && <RelationTypeForm definition={d} done={done} />}
                </div>
            )) : schema.property_definitions.map((d) => (
                <div key={d.property_id}>
                    <div className="flex items-center justify-between gap-2">
                        <span>{d.label} · {d.key} · {d.value_type}{d.unit ? ` (${d.unit})` : ''} · rev {d.revision}</span>
                        <span className="flex shrink-0 gap-1">
                            <button type="button" className={button} disabled={busy} onClick={() => setEditing(d.property_id)}>수정</button>
                            <button type="button" className={button} disabled={busy} onClick={() => void toggle(`/property-definitions/${d.property_id}`, !!d.active, d.revision)}>{d.active ? '비활성화' : '활성화'}</button>
                        </span>
                    </div>
                    {editing === d.property_id && <PropertyDefinitionForm definition={d} done={done} />}
                </div>
            ))}
            {error && <p role="alert" className="text-danger">{error}</p>}
        </div>
    );
}
