export type KnowledgeTab = 'graph' | 'terms';

const TABS: { key: KnowledgeTab; label: string }[] = [
    { key: 'graph', label: '그래프' },
    { key: 'terms', label: '용어집' },
];

/** 지식 그래프 화면의 탭 (그래프 / 용어집). 사양 관리 화면의 탭과 같은 모양 */
export function KnowledgeTabs({ current, onChange }: { current: KnowledgeTab; onChange: (tab: KnowledgeTab) => void }) {
    return (
        <div role="tablist" aria-label="지식 그래프 탭" className="flex shrink-0 p-0.5 rounded-lg bg-chip">
            {TABS.map((t) => (
                <button
                    key={t.key}
                    type="button"
                    role="tab"
                    aria-selected={current === t.key}
                    onClick={() => { if (t.key !== current) onChange(t.key); }}
                    className={`h-7 px-3 rounded-md text-[12px] font-semibold transition-colors ${
                        current === t.key ? 'bg-white text-ink shadow-[0_1px_2px_rgba(20,28,43,0.10)]' : 'text-muted hover:text-ink'
                    }`}
                >
                    {t.label}
                </button>
            ))}
        </div>
    );
}
