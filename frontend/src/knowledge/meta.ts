/** 그래프 화면의 이름표와 색. 종류 키는 백엔드 graph_rag/types.py 와 같다. */
import type { EntityType, GraphNode, RelationOrigin, RelationType } from './types';

export const ENTITY_META: Record<EntityType, { label: string; color: string; hint: string }> = {
    product: { label: '제품', color: '#00A4E4', hint: '제품 모델 (예: N5800, A650)' },
    component: { label: '부품', color: '#7C5CFF', hint: 'CPU, GPU, 메모리, 패널 등' },
    certification: { label: '인증', color: '#16A34A', hint: '안전확인 신고, 적합성 등록 등 인증 종류' },
    cert_number: { label: '인증번호', color: '#64748B', hint: '인증서·등록·신고·성적서 번호' },
    organization: { label: '기관', color: '#E19A00', hint: '회사·시험기관·발급기관' },
    standard: { label: '규격', color: '#DB2777', hint: '규격·표준·기준 (예: KN 32)' },
    concept: { label: '상위 개념', color: '#141C2B', hint: '여러 인증 종류를 묶는 개념 (예: KC 인증)' },
};

export const ENTITY_TYPES = Object.keys(ENTITY_META) as EntityType[];

export const RELATION_META: Record<RelationType, { label: string; hint: string }> = {
    has_component: { label: '부품', hint: '제품 → 부품' },
    has_certification: { label: '인증', hint: '제품 → 인증 종류' },
    has_number: { label: '번호', hint: '인증 종류·제품 → 인증번호' },
    issued_by: { label: '발급 기관', hint: '인증·번호 → 기관' },
    complies_with: { label: '규격 준수', hint: '제품·인증 → 규격' },
    part_of: { label: '상위 개념', hint: '인증 종류 → 상위 개념' },
};

export const RELATION_TYPES = Object.keys(RELATION_META) as RelationType[];

export const ORIGIN_META: Record<RelationOrigin, { label: string; className: string; stroke: string; dash?: string }> = {
    extract: { label: '문서 추출', className: 'border-line bg-white text-muted', stroke: '#B8C2CF' },
    seed: { label: '기본 개념', className: 'border-ink/15 bg-chip text-ink/70', stroke: '#8A96A8', dash: '5 4' },
    manual: { label: '담당자', className: 'border-brand/25 bg-brand-tint text-brand-hover', stroke: '#00A4E4' },
};

/** 노드 반지름: 관계가 많을수록 크게. 상위 개념은 항상 크게 */
export function nodeRadius(node: GraphNode): number {
    const base = 7 + Math.min(11, Math.sqrt(node.degree) * 2.6);
    return node.type === 'concept' ? Math.max(base, 15) : base;
}
