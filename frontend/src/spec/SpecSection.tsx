import { useCallback, useEffect, useState } from 'react';
import { AppHeader } from '../components/AppHeader';
import { specApi, type Component, type SpecAttribute, type SpecMeta } from './api';
import { AttributesTab } from './AttributesTab';
import { ComponentsTab } from './ComponentsTab';
import { ImportTab } from './ImportTab';
import { ProductsTab } from './ProductsTab';
import { errorMessage } from './styles';
import { Notice } from './ui';

/**
 * 제품·부품 사양 관리 (/spec).
 *
 * 세일즈 가이드 같은 문서는 근거로만 쓰고, 입찰 조건과 대조할 사양은 여기서 구조화해 관리한다.
 * 탭은 세 개다: 제품(모델별 사양·부품 구성), 부품(CPU·SSD 등 세부 사양), 속성(사양 항목 사전).
 * 속성 목록과 부품 목록은 탭 사이에 공유되므로 여기서 들고 있다.
 */

type Tab = 'products' | 'components' | 'attributes' | 'import';

const TABS: { key: Tab; label: string }[] = [
    { key: 'products', label: '제품' },
    { key: 'components', label: '부품' },
    { key: 'attributes', label: '속성' },
    { key: 'import', label: '표 가져오기' },
];

export function SpecSection() {
    // /spec?tab=import 처럼 주소로 탭을 열 수 있다 (안내 링크용)
    const [tab, setTab] = useState<Tab>(() => {
        const wanted = new URLSearchParams(window.location.search).get('tab');
        return TABS.some((t) => t.key === wanted) ? (wanted as Tab) : 'products';
    });
    const [meta, setMeta] = useState<SpecMeta | null>(null);
    const [attributes, setAttributes] = useState<SpecAttribute[] | null>(null);
    const [components, setComponents] = useState<Component[] | null>(null);
    const [loadError, setLoadError] = useState('');

    const reloadAttributes = useCallback(async () => {
        setAttributes(await specApi.listAttributes());
    }, []);

    const reloadComponents = useCallback(async () => {
        setComponents(await specApi.listComponents());
    }, []);

    const addDefaultAttributes = useCallback(async () => {
        await specApi.addDefaultAttributes();
        await reloadAttributes();
    }, [reloadAttributes]);

    useEffect(() => {
        let cancelled = false;
        Promise.all([specApi.meta(), specApi.listAttributes(), specApi.listComponents()])
            .then(([m, a, c]) => {
                if (cancelled) return;
                setMeta(m);
                setAttributes(a);
                setComponents(c);
            })
            .catch((e) => { if (!cancelled) setLoadError(errorMessage(e, '사양 정보를 불러오지 못했습니다. 백엔드가 최신 코드로 떠 있는지 확인하세요.')); });
        return () => { cancelled = true; };
    }, []);

    return (
        <div className="min-h-screen md:h-dvh md:overflow-hidden bg-white text-ink font-sans antialiased flex flex-col">
            <AppHeader current="spec">
                <div role="tablist" aria-label="사양 관리 탭" className="flex p-0.5 rounded-lg bg-chip">
                    {TABS.map((t) => (
                        <button
                            key={t.key}
                            type="button"
                            role="tab"
                            aria-selected={tab === t.key}
                            onClick={() => setTab(t.key)}
                            className={`h-7 px-3 rounded-md text-[12px] font-semibold transition-colors ${
                                tab === t.key ? 'bg-white text-ink shadow-[0_1px_2px_rgba(20,28,43,0.10)]' : 'text-muted hover:text-ink'
                            }`}
                        >
                            {t.label}
                            {t.key === 'attributes' && attributes !== null && <span className="ml-1 text-muted tabular-nums">{attributes.length}</span>}
                            {t.key === 'components' && components !== null && <span className="ml-1 text-muted tabular-nums">{components.length}</span>}
                        </button>
                    ))}
                </div>
            </AppHeader>

            {loadError ? (
                <div className="p-6"><Notice kind="error">{loadError}</Notice></div>
            ) : tab === 'products' ? (
                <ProductsTab
                    meta={meta}
                    attributes={attributes ?? []}
                    components={components ?? []}
                    onAddDefaultAttributes={addDefaultAttributes}
                    onComponentsChanged={() => void reloadComponents()}
                />
            ) : tab === 'components' ? (
                <ComponentsTab
                    meta={meta}
                    attributes={attributes ?? []}
                    components={components}
                    onChanged={reloadComponents}
                    onAddDefaultAttributes={addDefaultAttributes}
                />
            ) : tab === 'attributes' ? (
                <AttributesTab meta={meta} attributes={attributes} onChanged={reloadAttributes} onAddDefaults={addDefaultAttributes} />
            ) : (
                <ImportTab
                    meta={meta}
                    attributes={attributes ?? []}
                    onImported={async (ownerType) => {
                        // 새 속성·부품이 생겼을 수 있으니 공유 목록을 다시 받는다
                        await reloadAttributes();
                        if (ownerType === 'component') await reloadComponents();
                    }}
                    onOpenTab={(next) => setTab(next)}
                />
            )}
        </div>
    );
}
