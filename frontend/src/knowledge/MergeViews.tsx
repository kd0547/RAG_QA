import { useEffect, useState } from 'react';

import { graphApi } from './api';
import { TypeDot } from './EntityPicker';
import { errorText } from './errors';
import { groupRelations } from './relationGroups';
import { entityMeta, useGraphSchema } from './schemaContext';
import type { GraphEntityDetail } from './types';

export interface MergeDone {
    /** 없어진 개체 */
    sourceId: number;
    /** 남은 개체 */
    targetId: number;
    /** 합친 뒤 보일 알림 */
    notice: string;
}

function documentCount(entity: GraphEntityDetail): number {
    return new Set(entity.mentions.map((m) => m.file_id)).size;
}

function EntityRow({ entity, keep }: { entity: GraphEntityDetail; keep: boolean }) {
    return (
        <div className={`rounded-lg border px-2.5 py-2 ${keep ? 'border-brand/40 bg-brand-tint/50' : 'border-line bg-surface'}`}>
            <div className="flex items-center gap-1.5">
                <span className={`shrink-0 rounded-full px-1.5 py-px text-[10.5px] font-bold ${keep ? 'bg-brand text-white' : 'bg-chip text-muted'}`}>
                    {keep ? '남음' : '없어짐'}
                </span>
                <TypeDot type={entity.type} />
                <span className={`min-w-0 flex-1 truncate text-[12.5px] font-bold ${keep ? '' : 'text-ink/60'}`} title={entity.name}>{entity.name}</span>
            </div>
            <p className="mt-1 text-[11px] text-muted">
                관계 {groupRelations(entity.relations).length} · 문서 {documentCount(entity)}
                {entity.ref_id && ' · 사양 DB 연결'}
            </p>
        </div>
    );
}

/**
 * 두 개체를 하나로 합치기 전 확인 창. a는 처음에 없어지는 쪽, b는 남는 쪽이고 ⇄로 바꾼다.
 * 사양 DB에 연결된 개체가 한쪽뿐이면 그쪽이 남게 시작한다. 두 개체 상세를 새로 읽어 수정 번호(revision)를 맞춘다.
 * 백엔드 규칙(POST /graph/entities/{id}/merge): 같은 종류끼리만, 서로 다른 사양 DB 대상끼리는 안 된다.
 */
export function MergeConfirm({ aId, bId, onCancel, onMerged }: {
    aId: number;
    bId: number;
    onCancel: () => void;
    onMerged: (done: MergeDone) => void;
}) {
    const { schema } = useGraphSchema();
    const [pair, setPair] = useState<{ a: GraphEntityDetail; b: GraphEntityDetail } | null>(null);
    const [loadError, setLoadError] = useState('');
    const [swapped, setSwapped] = useState(false);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    // aId·bId가 바뀌면 부모가 key로 새로 만든다
    useEffect(() => {
        let ignore = false;
        Promise.all([graphApi.entity(aId), graphApi.entity(bId)]).then(([a, b]) => {
            if (ignore) return;
            setPair({ a, b });
            setSwapped(!!a.ref_id && !b.ref_id);
        }).catch((e: unknown) => {
            if (!ignore) setLoadError(errorText(e));
        });
        return () => { ignore = true; };
    }, [aId, bId]);

    if (loadError) {
        return (
            <div>
                <p role="alert" className="text-[12px] text-danger">{loadError}</p>
                <div className="mt-2 flex justify-end">
                    <button type="button" onClick={onCancel} className="h-7 rounded-md px-2 text-[11.5px] font-semibold text-muted hover:bg-chip">닫기</button>
                </div>
            </div>
        );
    }
    if (!pair) return <p className="text-[12px] text-muted">불러오는 중…</p>;

    const source = swapped ? pair.b : pair.a;
    const target = swapped ? pair.a : pair.b;
    const blocked = source.type !== target.type
        ? `종류가 달라 합칠 수 없습니다 (${entityMeta(schema, source.type).label} · ${entityMeta(schema, target.type).label}).`
        : source.ref_id && target.ref_id && (source.ref_type !== target.ref_type || source.ref_id !== target.ref_id)
            ? '두 개체가 서로 다른 사양 DB 항목에 연결돼 있어 합칠 수 없습니다. 사양 DB에서 먼저 정리하세요.'
            : '';
    // 다른 표기로 남는 이름 (남는 개체에 이미 있는 표기는 빼고)
    const known = new Set([target.name, ...target.aliases].map((n) => n.trim().toLowerCase()));
    const newAliases = [...new Set([source.name, ...source.aliases])].filter((n) => !known.has(n.trim().toLowerCase()));
    // 둘 사이의 관계는 합치면 자기 자신을 가리키게 되어 지워진다
    const between = groupRelations(source.relations.filter((r) => r.source_id === target.id || r.target_id === target.id)).length;

    const merge = async () => {
        setBusy(true);
        setError('');
        try {
            const merged = await graphApi.mergeEntity(source.id, target.id, source.revision, target.revision);
            onMerged({
                sourceId: source.id,
                targetId: merged.id,
                notice: `합쳤습니다: ${source.name} → ${merged.name}${newAliases.length ? ` (다른 표기에 ${newAliases.join(', ')} 추가)` : ''}`,
            });
        } catch (e) {
            setError(errorText(e));
            setBusy(false);
        }
    };

    return (
        <div>
            <p className="text-[12.5px] font-bold">같은 개체로 합치기</p>
            <div className="mt-2">
                <EntityRow entity={target} keep />
                <div className="flex justify-center py-1">
                    <button type="button" onClick={() => setSwapped(!swapped)} disabled={busy}
                        title="어느 개체를 남길지 바꿉니다"
                        className="h-6 rounded-full border border-line bg-white px-2.5 text-[11px] font-semibold text-ink/75 hover:bg-chip disabled:opacity-50">
                        ⇅ 남길 개체 바꾸기
                    </button>
                </div>
                <EntityRow entity={source} keep={false} />
            </div>
            {blocked ? (
                <p role="alert" className="mt-2 rounded-md bg-danger-surface px-2 py-1.5 text-[11.5px] leading-5 text-danger">{blocked}</p>
            ) : (
                <ul className="mt-2 list-disc space-y-0.5 pl-4 text-[11.5px] leading-5 text-ink/75">
                    <li>관계와 문서 위치가 남는 개체로 옮겨집니다.</li>
                    {newAliases.length > 0 && <li>다른 표기로 남는 이름: {newAliases.join(', ')}</li>}
                    {between > 0 && <li>둘 사이의 관계 {between}개는 지워집니다.</li>}
                </ul>
            )}
            {error && <p role="alert" className="mt-2 text-[11.5px] text-danger">{error}</p>}
            <div className="mt-2.5 flex justify-end gap-1.5">
                <button type="button" onClick={onCancel} className="h-7 rounded-md px-2 text-[11.5px] font-semibold text-muted hover:bg-chip">취소</button>
                <button type="button" disabled={busy || !!blocked} onClick={() => void merge()}
                    className="h-7 rounded-md bg-ink px-2.5 text-[11.5px] font-bold text-white disabled:opacity-40">
                    {busy ? '합치는 중…' : '합치기'}
                </button>
            </div>
        </div>
    );
}
