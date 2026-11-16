import { useEffect, useState } from 'react';

import { request } from '../lib/http';
import { errorText } from './errors';
import { entityMeta, typeKeys, useGraphSchema } from './schemaContext';
import type { GraphEntityDetail } from './types';
import { graphWrite } from './write';

/**
 * 편집 제한 해제 (지시서 GR5) 화면 조각.
 * - TypeChanger: 개체 종류 바꾸기. 사양 노드면 투영이 종류를 되돌리지 않는다 (type_locked)
 * - SpecDiffBox: "사양 DB와 다름" 표시와 "사양 DB 기준으로 되돌리기"
 * - RuleWarnings: 규칙(허용 종류·식별자)과 다른 관계·개체 목록. 사람이 의도한 것이면 그대로 둔다
 */

export function TypeChanger({ entity, changed }: { entity: GraphEntityDetail; changed: () => void }) {
    const { schema } = useGraphSchema();
    const [busy, setBusy] = useState(false);
    const [message, setMessage] = useState('');
    const [error, setError] = useState('');
    if (!schema.editing_enabled) return null;
    const change = async (type: string) => {
        if (type === entity.type) return;
        setBusy(true); setError(''); setMessage('');
        try {
            const result = await graphWrite<GraphEntityDetail>(`/entities/${entity.id}`, 'PATCH', { type, expected_revision: entity.revision });
            setMessage([`종류를 ${entityMeta(schema, type).label}(으)로 바꿨습니다.${entity.ref_id ? ' 사양 DB를 다시 투영해도 이 종류를 유지합니다.' : ''}`,
                ...(result.warnings ?? [])].join(' '));
            changed();
        } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
    };
    return (
        <div className="mt-2 text-[11.5px]">
            <label className="flex items-center gap-1.5 text-muted">종류
                <select aria-label="개체 종류 바꾸기" value={entity.type} disabled={busy} onChange={(e) => void change(e.target.value)}
                    className="h-7 rounded-md border border-line bg-white px-1.5 text-[11.5px] font-semibold text-ink disabled:opacity-50">
                    {[...new Set([entity.type, ...typeKeys(schema)])].map((t) => <option key={t} value={t}>{entityMeta(schema, t).label}</option>)}
                </select>
            </label>
            {message && <p className="mt-1 rounded bg-warn-soft/50 px-1.5 py-1 text-ink/80">{message}</p>}
            {error && <p role="alert" className="mt-1 text-danger">{error}</p>}
        </div>
    );
}

export function SpecDiffBox({ entity, changed }: { entity: GraphEntityDetail; changed: () => void }) {
    const { schema } = useGraphSchema();
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');
    const diff = entity.spec_diff;
    if (!diff?.differs) return null;
    const reset = async () => {
        if (!window.confirm('이 노드에 대한 사람의 편집(지운 관계, 바꾼 종류·이름, 바꿔 넣은 관계)을 지우고 사양 DB 기준으로 다시 만듭니다. 사양 DB는 바뀌지 않습니다.')) return;
        setBusy(true); setError('');
        try {
            await graphWrite(`/entities/${entity.id}/reset-spec`, 'POST', { expected_revision: entity.revision });
            changed();
        } catch (e) { setError(errorText(e)); } finally { setBusy(false); }
    };
    return (
        <section aria-label="사양 DB와 다름" className="border-t border-divide px-4 py-3 text-[12px]">
            <div className="rounded-lg border border-warn/40 bg-warn-soft/40 p-2.5">
                <p className="font-bold">사양 DB와 다름</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[11.5px]">
                    {diff.type_changed && <li>사람이 종류를 바꿨습니다.</li>}
                    {diff.renamed && <li>사람이 표시 이름을 바꿨습니다.</li>}
                    {diff.excluded_relations.map((r) => (
                        <li key={`${r.type}-${r.source_id}-${r.target_id}-${r.source_key}`}>
                            지운 관계: {r.source_name} -{schema.relation_types.find((t) => t.key === r.type)?.label ?? r.type}→ {r.target_name}
                        </li>
                    ))}
                </ul>
                {schema.editing_enabled && <button type="button" disabled={busy} onClick={() => void reset()}
                    className="mt-2 h-7 rounded-md border border-line bg-white px-2 text-[11.5px] font-semibold hover:bg-chip disabled:opacity-50">사양 DB 기준으로 되돌리기</button>}
                <p className="mt-1.5 text-[11px] text-muted">그래프 편집은 사양 DB를 고치지 않습니다. 값은 사양 화면에서 바꿉니다.</p>
                {error && <p role="alert" className="mt-1 text-danger">{error}</p>}
            </div>
        </section>
    );
}

interface RuleWarningList {
    relations: { id: number; label: string; reason: string; origin: string; source_id: number; source_name: string; source_type: string;
        target_id: number; target_name: string; target_type: string; original_name: string | null; page: number | null }[];
    entities: { id: number; type: string; name: string; creation_origin: string }[];
    counts: { relations: number; entities: number; relations_by_origin: Record<string, number>; entities_by_origin: Record<string, number> };
}

const ORIGIN_LABEL: Record<string, string> = { extract: '문서 추출', spec: '사양 DB', manual: '사용자 입력', legacy: '기존 데이터', seed: '옛 기본 연결' };
const byOrigin = (counts: Record<string, number>) => Object.entries(counts).map(([k, v]) => `${ORIGIN_LABEL[k] ?? k} ${v}`).join(' · ') || '없음';

export function RuleWarnings({ onSelect }: { onSelect: (id: number) => void }) {
    const { schema } = useGraphSchema();
    const [data, setData] = useState<RuleWarningList | null>(null);
    const [error, setError] = useState('');
    useEffect(() => {
        request<RuleWarningList>('/graph/rule-warnings').then(setData).catch((e: Error) => setError(e.message));
    }, []);
    if (error) return <p role="alert" className="text-sm text-danger">{error}</p>;
    if (!data) return <p className="text-sm text-muted">불러오는 중…</p>;
    return (
        <div className="space-y-3 text-xs">
            <p className="text-muted">규칙은 문서 자동 추출만 거릅니다. 사람이 의도한 것이면 그대로 두세요. 항목을 누르면 그 개체로 갑니다.</p>
            <section>
                <h3 className="font-bold">허용 종류를 어기는 관계 {data.counts.relations} <span className="font-normal text-muted">({byOrigin(data.counts.relations_by_origin)})</span></h3>
                <ul className="mt-1 space-y-1">
                    {data.relations.map((r) => (
                        <li key={r.id}>
                            <button type="button" onClick={() => onSelect(r.source_id)} className="w-full rounded border border-warn/30 bg-warn-soft/30 px-2 py-1 text-left hover:bg-warn-soft/60">
                                {r.source_name}({entityMeta(schema, r.source_type).label}) -{r.label}→ {r.target_name}({entityMeta(schema, r.target_type).label})
                                <span className="text-muted"> · {ORIGIN_LABEL[r.origin] ?? r.origin}{r.original_name ? ` · ${r.original_name}${r.page ? ` p${r.page}` : ''}` : ''} · {r.reason}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            </section>
            <section>
                <h3 className="font-bold">식별자 규칙을 어기는 개체 {data.counts.entities} <span className="font-normal text-muted">({byOrigin(data.counts.entities_by_origin)})</span></h3>
                <ul className="mt-1 flex flex-wrap gap-1">
                    {data.entities.map((e) => (
                        <li key={e.id}>
                            <button type="button" onClick={() => onSelect(e.id)} className="rounded border border-line px-1.5 py-0.5 hover:bg-chip" title={ORIGIN_LABEL[e.creation_origin] ?? e.creation_origin}>
                                {e.name} <span className="text-muted">{entityMeta(schema, e.type).label}</span>
                            </button>
                        </li>
                    ))}
                </ul>
            </section>
        </div>
    );
}
