import { useEffect, useState } from 'react';
import { request } from '../lib/http';
import { linkProps } from '../lib/router';
import { EntityTypeManager } from './EntityTypes';
import { DefinitionList } from './DefinitionEditors';
import { RuleWarnings } from './EntityEditExtras';
import { entityMeta, typeKeys, useGraphSchema } from './schemaContext';
import type { PropertyDefinition } from './schemaContext';
import type { EntityType, GraphEntityDetail, PropertyValue } from './types';
import { graphWrite } from './write';

const input = 'w-full rounded border border-line bg-white px-2 py-1.5 text-sm';
const button = 'rounded border border-line bg-white px-3 py-1.5 text-xs font-semibold hover:bg-chip disabled:opacity-50';
const primary = `${button} bg-brand text-white`;
interface EditEvent { event_id: number; target_kind: string; target_id: string; action: string; actor_label: string;
    created_at: string; before_json: string; after_json: string; result_revision: number }
function History({ entityId }: { entityId?: number }) {
    const [rows, setRows] = useState<EditEvent[]>([]);
    const [offset, setOffset] = useState(0);
    const [error, setError] = useState('');
    useEffect(() => {
        request<EditEvent[]>(`/graph/changes?limit=25&offset=${offset}${entityId ? `&kind=entity&target_id=${entityId}` : ''}`)
            .then(setRows).catch((e: Error) => setError(e.message));
    }, [entityId, offset]);
    return <div className="space-y-2 text-xs">
        {error && <p role="alert">{error}</p>}
        {rows.length === 0 && <p>변경 이력이 없습니다.</p>}
        {rows.map((r) => <details key={r.event_id} className="rounded border border-line p-2">
            <summary>{r.created_at} · {r.target_kind} #{r.target_id} · {r.action} · rev {r.result_revision} · {r.actor_label || '담당자 미입력'} (본인 확인 안 됨)</summary>
            <p className="mt-2 font-semibold">변경 전</p><pre className="whitespace-pre-wrap break-all">{r.before_json}</pre>
            <p className="mt-2 font-semibold">변경 후</p><pre className="whitespace-pre-wrap break-all">{r.after_json}</pre>
        </details>)}
        <div className="flex gap-2"><button className={button} disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 25))}>이전</button>
            <button className={button} disabled={rows.length < 25} onClick={() => setOffset(offset + 25)}>다음</button></div>
    </div>;
}

export function TypeChoices({ label, values, change }: { label: string; values: EntityType[]; change: (v: EntityType[]) => void }) {
    const { schema } = useGraphSchema();
    return <fieldset className="rounded border border-line p-2"><legend className="text-xs">{label}</legend><div className="flex flex-wrap gap-2">
        {typeKeys(schema).map((t) => <label key={t} className="text-xs"><input type="checkbox" checked={values.includes(t)}
            onChange={() => change(values.includes(t) ? values.filter((v) => v !== t) : [...values, t])} /> {entityMeta(schema, t).label}</label>)}
    </div></fieldset>;
}

export function GraphEditingToolbar({ onChanged, onSelect }: { onChanged: () => void; onSelect: (id: number) => void }) {
    const { schema, refresh, error: schemaError } = useGraphSchema();
    const [mode, setMode] = useState('');
    const [name, setName] = useState('');
    const [key, setKey] = useState('');
    const [entityType, setEntityType] = useState<EntityType>('product');
    const [valueType, setValueType] = useState<PropertyDefinition['value_type']>('text');
    const [unit, setUnit] = useState('');
    const [choices, setChoices] = useState('');
    const [description, setDescription] = useState('');
    const [sourceTypes, setSourceTypes] = useState<EntityType[]>([]);
    const [targetTypes, setTargetTypes] = useState<EntityType[]>([]);
    const [multiple, setMultiple] = useState(false);
    const [allowSelf, setAllowSelf] = useState(false);
    const [actor, setActor] = useState(sessionStorage.getItem('graph-edit-actor') ?? '');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [deleted, setDeleted] = useState<{ entity: { id: number; name: string; revision: number }[]; relation: { id: number; type: string; origin: string; revision: number }[] }>({ entity: [], relation: [] });
    const [offset, setOffset] = useState(0);
    const [specQuery, setSpecQuery] = useState('');
    const [specOptions, setSpecOptions] = useState<{ id: string; model: string }[]>([]);
    const [specId, setSpecId] = useState('');
    useEffect(() => {
        if (mode !== 'deleted') return;
        request<typeof deleted>(`/graph/deleted?limit=25&offset=${offset}`).then(setDeleted).catch((e: Error) => setError(e.message));
    }, [mode, offset]);
    useEffect(() => {
        if (mode !== 'entity' || !['product', 'component'].includes(entityType)) return;
        let ignore = false;
        const timer = setTimeout(() => {
            request<{ id: string; model: string }[]>(`/specs/${entityType === 'product' ? 'products' : 'components'}?q=${encodeURIComponent(specQuery)}`)
                .then((items) => { if (!ignore) setSpecOptions(items); }).catch(() => { if (!ignore) setSpecOptions([]); });
        }, 250);
        return () => { ignore = true; clearTimeout(timer); };
    }, [mode, entityType, specQuery]);
    const run = async (action: () => Promise<void>) => {
        setBusy(true); setError('');
        try { sessionStorage.setItem('graph-edit-actor', actor); await action(); refresh(); onChanged(); }
        catch (e) { setError(e instanceof Error ? e.message : String(e)); }
        finally { setBusy(false); }
    };
    const save = () => run(async () => {
        if (mode === 'entity') {
            const result = await graphWrite<{ id: number }>('/entities', 'POST', { type: entityType, name, aliases: [],
                ...(specId ? { ref_type: entityType, ref_id: specId } : {}) });
            onSelect(result.id);
        } else if (mode === 'property') {
            await graphWrite('/property-definitions', 'POST', { key: `custom:${key}`, label: name, value_type: valueType,
                unit: valueType === 'number' ? unit || null : null, allowed_values: valueType === 'enum' ? choices.split(',').map((s) => s.trim()).filter(Boolean) : [],
                allowed_entity_types: sourceTypes, multiple });
        } else {
            await graphWrite('/relation-types', 'POST', { key: `custom:${key}`, label: name, description,
                source_entity_types: sourceTypes, target_entity_types: targetTypes, allow_self: allowSelf });
        }
        setName(''); setKey(''); setMode('');
    });
    return <div className="border-b border-line bg-white px-3 py-2">
        {schemaError && <p role="alert" className="text-danger">{schemaError}</p>}
        <div className="flex flex-wrap gap-2">
            {schema.editing_enabled && [['entity', '객체 추가'], ['types', '개체 종류'], ['property', '속성 정의'], ['relation', '관계 종류']].map(([m, label]) =>
                <button key={m} className={button} onClick={() => { setMode(m); setError(''); setSourceTypes(typeKeys(schema)); setTargetTypes(typeKeys(schema)); }}>{label}</button>)}
            <button className={button} onClick={() => setMode('warnings')}>규칙 위반 목록</button>
            <button className={button} onClick={() => setMode('history')}>변경 이력</button>
            <button className={button} onClick={() => setMode('deleted')}>삭제된 항목</button>
            {!schema.editing_enabled && <span className="text-xs text-muted">읽기 전용</span>}
        </div>
        {mode && <div role="dialog" aria-modal="true" aria-label="그래프 관리" className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4">
            <div className="max-h-[85vh] w-full max-w-xl overflow-auto rounded-xl bg-white p-5 shadow-xl">
                <div className="mb-4 flex items-center justify-between"><h2 className="font-bold">{{ entity: '객체 추가', types: '개체 종류', property: '그래프 추가 정보 정의', relation: '관계 종류 등록', warnings: '규칙 위반 목록', history: '변경 이력', deleted: '삭제된 항목' }[mode]}</h2>
                    <button aria-label="관리 창 닫기" className={button} onClick={() => setMode('')}>닫기</button></div>
                {mode === 'history' ? <History /> : mode === 'warnings' ? <RuleWarnings onSelect={(id) => { setMode(''); onSelect(id); }} /> : mode === 'types' ? <EntityTypeManager onChanged={onChanged} /> : mode === 'deleted' ? <div className="space-y-2">
                    <p className="text-xs text-muted">삭제된 상대 객체와 비활성 종류는 자동 복구하지 않습니다.</p>
                    {deleted.entity.map((e) => <div key={e.id} className="flex items-center justify-between text-sm">#{e.id} {e.name}
                        {schema.editing_enabled && <button className={button} disabled={busy} onClick={() => void run(async () => {
                            const result = await graphWrite<{ review_relations: unknown[] }>(`/entities/${e.id}/restore`, 'POST', { expected_revision: e.revision });
                            setDeleted({ ...deleted, entity: deleted.entity.filter((r) => r.id !== e.id) });
                            onSelect(e.id);
                            if (result.review_relations.length) setError(`객체를 복구했습니다. 상대 객체 또는 종류 상태 확인이 필요한 관계 ${result.review_relations.length}개가 있습니다.`);
                        })}>복구</button>}</div>)}
                    {deleted.relation.map((r) => <div key={r.id} className="flex items-center justify-between text-sm">관계 #{r.id} {r.type} ({r.origin})
                        {schema.editing_enabled && r.origin === 'manual' && <button className={button} disabled={busy} onClick={() => void run(async () => {
                            await graphWrite(`/relations/${r.id}/restore`, 'POST', { expected_revision: r.revision });
                            setDeleted({ ...deleted, relation: deleted.relation.filter((v) => v.id !== r.id) });
                        })}>복구</button>}</div>)}
                    {!deleted.entity.length && !deleted.relation.length && <p className="text-sm">삭제된 항목이 없습니다.</p>}
                    <button className={button} disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 25))}>이전</button>{' '}
                    <button className={button} disabled={deleted.entity.length < 25 && deleted.relation.length < 25} onClick={() => setOffset(offset + 25)}>다음</button>
                </div> : <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); void save(); }}>
                    <label className="block text-xs">담당자 표시 (본인 확인 안 됨)<input className={input} value={actor} onChange={(e) => setActor(e.target.value)} maxLength={100} /></label>
                    {mode === 'entity' && <><label className="block text-xs">객체 종류<select className={input} value={entityType} onChange={(e) => { setEntityType(e.target.value as EntityType); setSpecId(''); }}>
                        {typeKeys(schema).map((t) => <option key={t} value={t}>{entityMeta(schema, t).label}</option>)}</select></label>
                        {['product', 'component'].includes(entityType) && <div className="space-y-2 rounded bg-surface p-2">
                            <label className="block text-xs">기존 사양 DB 항목 검색<input className={input} value={specQuery} onChange={(e) => setSpecQuery(e.target.value)} /></label>
                            <select aria-label="사양 DB 연결" className={input} value={specId} onChange={(e) => { setSpecId(e.target.value); const item = specOptions.find((v) => v.id === e.target.value); if (item) setName(item.model); }}>
                                <option value="">그래프 객체만 생성</option>{specOptions.map((v) => <option key={v.id} value={v.id}>{v.model}</option>)}</select>
                            <a {...linkProps('/spec')} className="text-xs text-brand underline">신규 관리 제품·부품은 사양 화면에서 등록</a></div>}</>}
                    <label className="block text-xs">{mode === 'entity' ? '객체 이름' : '표시 이름'}<input required className={input} value={name} onChange={(e) => setName(e.target.value)} maxLength={100} disabled={!!specId && mode === 'entity'} /></label>
                    {mode !== 'entity' && <label className="block text-xs">내부 키 (custom: 뒤의 영문)<input required pattern="[a-z][a-z0-9_-]*" className={input} value={key} onChange={(e) => setKey(e.target.value)} /></label>}
                    {mode === 'property' && <><p className="text-xs">검토 메모 등 그래프 추가 정보입니다. RAM·중량·인증번호 등 기술 사양은 <a {...linkProps('/spec')} className="text-brand underline">제품 사양에서 등록</a>하세요.</p>
                        <label className="block text-xs">자료형<select className={input} value={valueType} onChange={(e) => setValueType(e.target.value as PropertyDefinition['value_type'])}>
                            {['text', 'number', 'boolean', 'date', 'enum'].map((v) => <option key={v}>{v}</option>)}</select></label>
                        {valueType === 'number' && <label className="block text-xs">단위<input className={input} value={unit} onChange={(e) => setUnit(e.target.value)} /></label>}
                        {valueType === 'enum' && <label className="block text-xs">선택지 (쉼표로 구분)<input className={input} required value={choices} onChange={(e) => setChoices(e.target.value)} /></label>}
                        <TypeChoices label="적용 객체 종류" values={sourceTypes} change={setSourceTypes} />
                        <label className="block text-xs"><input type="checkbox" checked={multiple} onChange={(e) => setMultiple(e.target.checked)} /> 복수 값 허용</label></>}
                    {mode === 'relation' && <><TypeChoices label="출발 객체 종류 →" values={sourceTypes} change={setSourceTypes} />
                        <TypeChoices label="→ 도착 객체 종류" values={targetTypes} change={setTargetTypes} />
                        <label className="block text-xs">설명<textarea className={input} value={description} onChange={(e) => setDescription(e.target.value)} maxLength={4000} /></label>
                        <label className="block text-xs"><input type="checkbox" checked={allowSelf} onChange={(e) => setAllowSelf(e.target.checked)} /> 자기 연결 허용</label>
                        <p className="text-xs text-muted">새 관계는 자동 추론이나 사양 상속 규칙을 만들지 않습니다.</p></>}
                    <button className={primary} disabled={busy}>등록</button>
                    {(mode === 'property' || mode === 'relation') && <DefinitionList mode={mode} onChanged={onChanged} />}
                </form>}
                {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
            </div>
        </div>}
    </div>;
}

export function EntityProperties({ entity, changed, removed }: { entity: GraphEntityDetail; changed: () => void; removed: () => void }) {
    const { schema } = useGraphSchema();
    const [definitionId, setDefinitionId] = useState('');
    const [value, setValue] = useState('');
    const [confirmation, setConfirmation] = useState('confirmed');
    const [reason, setReason] = useState('');
    const [fileId, setFileId] = useState('');
    const [page, setPage] = useState('');
    const [edit, setEdit] = useState<PropertyValue | null>(null);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [aliases, setAliases] = useState('');
    const [impact, setImpact] = useState<{ relations: unknown[]; properties: unknown[]; mentions: unknown[]; entity: { revision: number } } | null>(null);
    const definition = schema.property_definitions.find((d) => d.property_id === Number(definitionId));
    const run = async (fn: () => Promise<void>) => {
        setError(''); setBusy(true);
        try { await fn(); changed(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
    };
    const save = () => run(async () => {
        if (!definition) return;
        if (definition.value_type === 'number' && !value.trim() && confirmation === 'confirmed') throw new Error('숫자를 입력하세요.');
        const typed = confirmation !== 'confirmed' && !value ? null : definition.value_type === 'number' ? Number(value) : definition.value_type === 'boolean' ? value === 'true' : value;
        await graphWrite(`/entities/${entity.id}/properties${edit ? `/${edit.value_id}` : ''}`, edit ? 'PATCH' : 'POST', {
            property_id: definition.property_id, value: typed, confirmation, expected_revision: edit?.revision,
            source: { reason, file_id: fileId || null, page: page ? Number(page) : null },
        });
        setEdit(null); setValue(''); setReason('');
    });
    return <section className="space-y-3 border-t border-line p-4 text-xs">
        <p>출처: {entity.creation_origin === 'manual' ? '사용자 입력' : entity.creation_origin === 'spec' ? '사양 DB' : entity.creation_origin === 'extract' ? '문서 추출' : '기존 데이터'} · rev {entity.revision}</p>
        <div className="rounded bg-surface p-2"><b>제품 사양 / 그래프 추가 정보</b><p className="mt-1">기술 사양·구성 변경은 사양 DB에 저장합니다.</p>
            <a {...linkProps(`/spec${entity.ref_id ? `?tab=${entity.ref_type === 'component' ? 'components' : 'products'}&${entity.ref_type}=${encodeURIComponent(entity.ref_id)}` : ''}`)} className="text-brand underline">제품 사양 조회·수정{entity.ref_id ? ` (${entity.ref_type})` : ''}</a></div>
        <h3 className="font-bold">그래프 추가 속성</h3>
        {entity.properties.map((p) => <div key={p.value_id} className="space-y-1 rounded border border-line p-2">
            <p><b>{p.label}</b>: {p.value === null ? '값 없음' : String(p.value)} {p.unit} · {p.confirmation === 'confirmed' ? '사용자 확정' : p.confirmation === 'unsupported' ? '명시적 미지원' : '미확정'} · rev {p.revision}</p>
            {p.sources.map((s) => <p key={s.source_id} className="text-muted">{s.file_deleted ? '근거 파일 삭제됨 · ' : ''}{s.source_name || '사용자 입력'}{s.page ? ` · ${s.page}쪽` : ''} · {s.reason || '사유 없음'} · 파일 검증 미완료</p>)}
            {schema.editing_enabled && <div className="flex gap-2"><button className={button} onClick={() => { setEdit(p); setDefinitionId(String(p.property_id)); setValue(p.value === null ? '' : String(p.value)); setConfirmation(p.confirmation); }}>수정</button>
                <button className={button} disabled={busy} onClick={() => void run(async () => { await graphWrite(`/entities/${entity.id}/properties/${p.value_id}?expected_revision=${p.revision}`, 'DELETE'); })}>삭제</button></div>}
        </div>)}
        {schema.editing_enabled && <><form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void save(); }}>
            <label className="block">추가 속성<select className={input} value={definitionId} disabled={!!edit} onChange={(e) => { setDefinitionId(e.target.value); setValue(''); }}>
                <option value="">속성 선택 (상단에서 새 정의 등록)</option>{schema.property_definitions.filter((d) => d.active && d.allowed_entity_types.includes(entity.type)).map((d) => <option key={d.property_id} value={d.property_id}>{d.label} {d.unit}</option>)}</select></label>
            {definition && <><label className="block">값 {definition.unit}
                {definition.value_type === 'enum' || definition.value_type === 'boolean' ? <select className={input} value={value} onChange={(e) => setValue(e.target.value)} required={confirmation === 'confirmed'}><option value="">선택</option>
                    {(definition.value_type === 'enum' ? definition.allowed_values : ['true', 'false']).map((v) => <option key={v}>{v}</option>)}</select>
                    : <input className={input} type={definition.value_type === 'date' ? 'date' : definition.value_type === 'number' ? 'number' : 'text'} step="any" maxLength={4000} value={value} onChange={(e) => setValue(e.target.value)} required={confirmation === 'confirmed'} />}</label>
                <label className="block">확인 상태<select className={input} value={confirmation} onChange={(e) => setConfirmation(e.target.value)}><option value="confirmed">사용자 확정</option><option value="uncertain">미확정</option><option value="unsupported">명시적 미지원</option></select></label>
                <label className="block">입력 사유<textarea className={input} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={4000} /></label>
                <label className="block">근거 파일 ID (선택)<input className={input} value={fileId} onChange={(e) => setFileId(e.target.value)} /></label>
                <label className="block">근거 페이지 (선택)<input className={input} type="number" min={1} value={page} onChange={(e) => setPage(e.target.value)} /></label>
                <p className="text-muted">파일을 선택해도 내용이 자동 검증되지는 않습니다.</p>
                <button className={primary} disabled={busy}>{edit ? '속성 수정 저장' : '속성 추가'}</button>{edit && <button type="button" className={button} onClick={() => setEdit(null)}>취소</button>}</>}
        </form>
            <details><summary className="cursor-pointer font-semibold">별칭 추가</summary><input aria-label="추가 별칭" className={input} value={aliases} onChange={(e) => setAliases(e.target.value)} placeholder="쉼표로 구분" />
                <button className={button} disabled={busy || !aliases.trim()} onClick={() => void run(async () => { await graphWrite(`/entities/${entity.id}`, 'PATCH', { aliases: aliases.split(',').map((s) => s.trim()).filter(Boolean), expected_revision: entity.revision }); setAliases(''); })}>별칭 저장</button>
                <p className="mt-1 text-muted">삭제한 표기도 재추출 시 같은 객체를 찾는 과거 식별자로 보존됩니다.</p>
                {entity.aliases.filter((a) => a !== entity.name).map((a) => <div key={a} className="flex items-center justify-between">{a}<button className={button} disabled={busy} onClick={() => void run(async () => {
                    await graphWrite(`/entities/${entity.id}`, 'PATCH', { remove_aliases: [a], expected_revision: entity.revision });
                })}>별칭 삭제</button></div>)}
            </details>
            <button className={`${button} text-danger`} disabled={busy} onClick={() => void run(async () => { setImpact(await request(`/graph/entities/${entity.id}/delete-impact`)); })}>그래프에서 제외</button>
            {impact && <div className="space-y-2 rounded border border-danger/30 p-2"><p>관계 {impact.relations.length}개 · 속성 {impact.properties.length}개 · 문서 위치 {impact.mentions.length}개{entity.ref_id ? ' · 사양 DB 연결 있음' : ''}</p>
                <p>원본 문서와 사양은 유지됩니다. 같은 객체 ID로 복구할 수 있습니다.</p>
                <button className={button} disabled={busy} onClick={() => void run(async () => { await graphWrite(`/entities/${entity.id}?expected_revision=${impact.entity.revision}`, 'DELETE'); removed(); })}>제외 확정</button>{' '}
                <button className={button} onClick={() => setImpact(null)}>취소</button></div>}
        </>}
        <details><summary className="cursor-pointer font-semibold">객체 변경 이력</summary><History entityId={entity.id} /></details>
        {error && <p role="alert" className="text-danger">{error}</p>}
    </section>;
}

