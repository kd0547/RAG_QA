/**
 * 같은 관계(출발·종류·도착) 묶기. 문서에서 뽑은 관계는 근거 페이지마다 한 행이라, 화면에서는 하나로 묶어 보이고
 * 근거만 여러 개로 보인다. 데이터(행)는 그대로다 — 페이지별 다시 뽑기·출처별 제외에 쓰인다.
 */
import type { GraphEdge, GraphRelation } from './types';

export function relationKey(r: { source: number; target: number; type: string } | GraphRelation): string {
    return 'source_id' in r ? `${r.source_id}|${r.type}|${r.target_id}` : `${r.source}|${r.type}|${r.target}`;
}

/** 처음 나온 순서를 지켜 같은 관계끼리 묶는다. 대표는 사람이 넣은 관계 → 사양 DB → 문서 순서 */
export function groupRelations<T extends GraphRelation | GraphEdge>(items: T[]): T[][] {
    const groups = new Map<string, T[]>();
    for (const item of items) {
        const key = relationKey(item);
        groups.set(key, [...(groups.get(key) ?? []), item]);
    }
    const rank = (r: T) => (r.origin === 'manual' ? 0 : r.origin === 'spec' ? 1 : 2);
    return [...groups.values()].map((list) => [...list].sort((a, b) => rank(a) - rank(b) || a.id - b.id));
}
