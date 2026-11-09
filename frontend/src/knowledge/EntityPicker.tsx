import { useEffect, useId, useState } from 'react';

import { graphApi } from './api';
import { ENTITY_META, ENTITY_TYPES } from './meta';
import type { EntityType, GraphEntitySummary } from './types';

export type PickedEntity =
    | { kind: 'existing'; id: number; type: EntityType; name: string }
    | { kind: 'new'; type: EntityType; name: string };

export function TypeDot({ type, className = 'w-2 h-2' }: { type: EntityType; className?: string }) {
    return <span aria-hidden className={`inline-block shrink-0 rounded-full ${className}`} style={{ background: ENTITY_META[type].color }} />;
}

/**
 * 개체 검색 상자. 이름·별칭 일부로 찾는다.
 * allowCreate면 목록 끝에 "새 개체로 추가"가 붙고, 고른 종류로 새 개체를 만든다 (실제 생성은 관계를 저장할 때 서버가 한다).
 */
export function EntityPicker({
    label,
    placeholder = '이름 일부로 찾기',
    excludeId,
    allowCreate = false,
    defaultNewType = 'product',
    disabled = false,
    onPick,
}: {
    label: string;
    placeholder?: string;
    excludeId?: number;
    allowCreate?: boolean;
    defaultNewType?: EntityType;
    disabled?: boolean;
    onPick: (picked: PickedEntity) => void;
}) {
    const inputId = useId();
    const [text, setText] = useState('');
    const [results, setResults] = useState<GraphEntitySummary[]>([]);
    const [open, setOpen] = useState(false);
    const [newType, setNewType] = useState<EntityType>(defaultNewType);
    const [error, setError] = useState('');

    const q = text.trim();
    useEffect(() => {
        if (!q) return;
        let ignore = false;
        const timer = window.setTimeout(() => {
            graphApi.searchEntities(q, undefined, 12).then((list) => {
                if (!ignore) {
                    setResults(list);
                    setError('');
                }
            }).catch((e: unknown) => {
                if (!ignore) setError(e instanceof Error ? e.message : '검색 실패');
            });
        }, 180);
        return () => {
            ignore = true;
            window.clearTimeout(timer);
        };
    }, [q]);

    const visible = q ? results.filter((r) => r.id !== excludeId) : [];
    const exact = visible.some((r) => r.name.trim().toLowerCase() === q.toLowerCase() && r.type === newType);

    const pick = (picked: PickedEntity) => {
        onPick(picked);
        setText('');
        setResults([]);
        setOpen(false);
    };

    return (
        <div
            className="relative"
            onBlur={(e) => {
                // 목록 안(새 개체 종류 선택 등)으로 포커스가 옮겨 가면 닫지 않는다
                if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
            }}
        >
            <label htmlFor={inputId} className="sr-only">{label}</label>
            <input
                id={inputId}
                value={text}
                disabled={disabled}
                onChange={(e) => {
                    setText(e.target.value);
                    setOpen(true);
                }}
                onFocus={() => setOpen(true)}
                onKeyDown={(e) => {
                    if (e.key === 'Escape') setOpen(false);
                    if (e.key === 'Enter' && visible[0]) {
                        e.preventDefault();
                        pick({ kind: 'existing', id: visible[0].id, type: visible[0].type, name: visible[0].name });
                    }
                }}
                placeholder={placeholder}
                autoComplete="off"
                className="block h-9 w-full rounded-lg border border-line bg-white px-3 text-[12.5px] text-ink placeholder:text-muted focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/10 disabled:opacity-50"
            />
            {open && q && (
                <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-20 max-h-72 overflow-y-auto rounded-lg border border-line bg-white py-1 shadow-[0_6px_20px_rgba(20,28,43,0.12)]">
                    {error && <p className="px-3 py-2 text-[12px] text-danger">{error}</p>}
                    {visible.map((r) => (
                        <button
                            key={r.id}
                            type="button"
                            onMouseDown={(e) => e.preventDefault()}
                            onClick={() => pick({ kind: 'existing', id: r.id, type: r.type, name: r.name })}
                            className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[12.5px] hover:bg-chip"
                        >
                            <TypeDot type={r.type} />
                            <span className="min-w-0 flex-1 truncate">{r.name}</span>
                            <span className="shrink-0 text-[11px] text-muted">{ENTITY_META[r.type].label}</span>
                        </button>
                    ))}
                    {!visible.length && !error && <p className="px-3 py-2 text-[12px] text-muted">맞는 개체가 없습니다.</p>}
                    {allowCreate && !exact && (
                        <div className="mt-1 border-t border-divide px-3 pb-1 pt-2">
                            <p className="text-[11px] text-muted">새 개체로 추가</p>
                            <div className="mt-1.5 flex items-center gap-2">
                                <select
                                    aria-label="새 개체 종류"
                                    value={newType}
                                    onChange={(e) => setNewType(e.target.value as EntityType)}
                                    className="h-8 rounded-md border border-line bg-white px-1.5 text-[12px]"
                                >
                                    {ENTITY_TYPES.map((t) => <option key={t} value={t}>{ENTITY_META[t].label}</option>)}
                                </select>
                                <button
                                    type="button"
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() => pick({ kind: 'new', type: newType, name: q })}
                                    className="h-8 min-w-0 flex-1 truncate rounded-md bg-brand-tint px-2 text-left text-[12px] font-semibold text-brand-hover hover:bg-brand-pale"
                                >
                                    + “{q}”
                                </button>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
