/** 그래프 화면의 관계 출처 표시와 노드 크기. 개체 종류의 이름·색은 스키마 응답(schemaContext.entityMeta)을 쓴다. */
import type { GraphNode, RelationOrigin } from './types';

export const ORIGIN_META: Record<RelationOrigin, { label: string; className: string; stroke: string; dash?: string }> = {
    extract: { label: '문서 추출', className: 'border-line bg-white text-muted', stroke: '#B8C2CF' },
    seed: { label: '기본 개념', className: 'border-ink/15 bg-chip text-ink/70', stroke: '#8A96A8', dash: '5 4' },
    manual: { label: '사용자 입력', className: 'border-brand/25 bg-brand-tint text-brand-hover', stroke: '#00A4E4' },
    spec: { label: '사양 DB', className: 'border-[#7C5CFF]/25 bg-[#F3F0FF] text-[#5B3FD9]', stroke: '#7C5CFF', dash: '2 3' },
};

/** 노드 반지름: 관계가 많을수록 크게. 사양 값 노드는 작게 (여러 제품이 공유해 관계가 많아도 크게 보이지 않게) */
export function nodeRadius(node: GraphNode): number {
    if (node.type === 'spec_value') return 5;
    return 7 + Math.min(11, Math.sqrt(node.degree) * 2.6);
}
