/** 문서 그래프 API 클라이언트 (백엔드: app/routers/graph.py). 베이스 URL 규칙은 lib/http.ts 참고. */
import { request } from '../lib/http';
import type {
    EntityType,
    GraphEntityDetail,
    GraphEntitySummary,
    GraphRelation,
    GraphStats,
    GraphView,
    RelationCreateInput,
    RelationType,
} from './types';

export interface ViewQuery {
    entityId?: number | null;
    depth?: number;
    types?: EntityType[];
    fileId?: string | null;
    limit?: number;
}

function query(params: Record<string, string | number | null | undefined>): string {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (value !== null && value !== undefined && value !== '') search.set(key, String(value));
    }
    const text = search.toString();
    return text ? `?${text}` : '';
}

export const graphApi = {
    stats(): Promise<GraphStats> {
        return request<GraphStats>('/graph/stats');
    },

    view(q: ViewQuery = {}): Promise<GraphView> {
        return request<GraphView>(`/graph/view${query({
            entity_id: q.entityId,
            depth: q.depth,
            types: q.types?.length ? q.types.join(',') : undefined,
            file_id: q.fileId,
            limit: q.limit,
        })}`);
    },

    searchEntities(q: string, type?: EntityType, limit = 20): Promise<GraphEntitySummary[]> {
        return request<GraphEntitySummary[]>(`/graph/entities${query({ q, type, limit })}`);
    },

    entity(id: number): Promise<GraphEntityDetail> {
        return request<GraphEntityDetail>(`/graph/entities/${id}`);
    },

    renameEntity(id: number, name: string): Promise<GraphEntityDetail> {
        return request<GraphEntityDetail>(`/graph/entities/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) });
    },

    /** sourceId 개체를 targetId에 합친다. 합친 결과(target)를 돌려준다 */
    mergeEntity(sourceId: number, targetId: number): Promise<GraphEntityDetail> {
        return request<GraphEntityDetail>(`/graph/entities/${sourceId}/merge`, {
            method: 'POST',
            body: JSON.stringify({ target_id: targetId }),
        });
    },

    createRelation(input: RelationCreateInput): Promise<GraphRelation> {
        return request<GraphRelation>('/graph/relations', { method: 'POST', body: JSON.stringify(input) });
    },

    updateRelation(id: number, changes: { type?: RelationType; reverse?: boolean }): Promise<GraphRelation> {
        return request<GraphRelation>(`/graph/relations/${id}`, { method: 'PATCH', body: JSON.stringify(changes) });
    },

    deleteRelation(id: number): Promise<{ deleted: number }> {
        return request<{ deleted: number }>(`/graph/relations/${id}`, { method: 'DELETE' });
    },

    /** 저장된 페이지 텍스트로 다시 뽑는다 (백그라운드). 사람이 넣거나 지운 관계는 유지된다 */
    rebuild(fileId?: string): Promise<{ scheduled: string }> {
        return request(`/graph/rebuild${query({ file_id: fileId })}`, { method: 'POST' });
    },
};
