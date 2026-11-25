import { useEffect, useRef, useState } from 'react';
import { specApi, type Product, type ProductDetail, type SpecValue } from './api';
import { btnGhost, btnPrimary, errorMessage, inputCls } from './styles';
import { Field, Notice } from './ui';

/**
 * 제품 복사: 원본의 제품 정보·사양 값·부품 연결을 새 모델로 옮긴다 (서버에 복사 API가 없어 기존 API를 차례로 부른다).
 * 파생 모델은 원본과 1~2개만 다르므로, 복사한 뒤 새 제품 화면에서 다른 값만 고친다.
 * 중간에 실패해도 만든 제품은 남긴다 (어디까지 복사됐는지 알린다).
 */
type Placement = 'sibling' | 'child';

export interface CopyDone {
    product: ProductDetail;
    message: string;
}

async function copyValue(ownerId: string, v: SpecValue) {
    const input = {
        attribute_key: v.attribute_key,
        value_text: v.value_text || (v.value_num !== null ? String(v.value_num) : ''),
        is_option: v.is_option,
        note: v.note,
        source_page: v.source_page,
        source_note: v.source_note,
    };
    const owner = { owner_type: 'product' as const, owner_id: ownerId };
    try {
        await specApi.addValue(owner, { ...input, source_file_id: v.source_file_id });
    } catch (e) {
        // 출처 문서가 지워졌으면 출처 문서 없이 다시 넣는다
        if (!v.source_file_id) throw e;
        await specApi.addValue(owner, input);
    }
}

export function CopyProductDialog({ source, products, onDone, onCancel }: {
    source: ProductDetail;
    products: Product[];
    onDone: (done: CopyDone) => void;
    onCancel: () => void;
}) {
    const [model, setModel] = useState(`${source.model}-`);
    const [name, setName] = useState(source.name);
    // 원본이 하위 모델이면 형제로, 최상위 모델이면 원본의 하위로 시작한다
    const [placement, setPlacement] = useState<Placement>(source.parent_id ? 'sibling' : 'child');
    const [copySpecs, setCopySpecs] = useState(true);
    const [copyLinks, setCopyLinks] = useState(true);
    const [busy, setBusy] = useState(false);
    const [progress, setProgress] = useState('');
    const [error, setError] = useState('');
    const modelRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        const el = modelRef.current;
        el?.focus();
        el?.setSelectionRange(el.value.length, el.value.length);
    }, []);
    useEffect(() => {
        if (busy) return;
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [busy, onCancel]);

    const parentModel = source.parent_id ? products.find((p) => p.id === source.parent_id)?.model ?? '상위 모델' : null;
    const trimmed = model.trim();
    const duplicate = products.some((p) => p.model.trim().toLowerCase() === trimmed.toLowerCase());
    const canCopy = !busy && trimmed.length > 0 && trimmed !== `${source.model}-` && !duplicate;

    async function run() {
        if (!canCopy) return;
        setBusy(true);
        setError('');
        let created: ProductDetail;
        try {
            setProgress('제품 만드는 중…');
            created = await specApi.createProduct({
                model: trimmed, name: name.trim(), category: source.category, status: source.status, note: source.note,
                parent_id: placement === 'child' ? source.id : source.parent_id,
            });
        } catch (e) {
            setError(errorMessage(e, '제품을 만들지 못했습니다.'));
            setBusy(false);
            setProgress('');
            return;
        }
        const failedValues: string[] = [];
        const failedLinks: string[] = [];
        const values = copySpecs ? source.specs : [];
        const links = copyLinks ? source.components : [];
        for (const [i, v] of values.entries()) {
            setProgress(`사양 값 ${i + 1}/${values.length} 복사 중…`);
            try { await copyValue(created.id, v); } catch { failedValues.push(v.attribute_name || v.attribute_key); }
        }
        for (const [i, c] of links.entries()) {
            setProgress(`부품 연결 ${i + 1}/${links.length} 복사 중…`);
            try {
                await specApi.linkComponent(created.id, { component_id: c.id, is_option: c.is_option, note: c.link_note });
            } catch { failedLinks.push(c.model); }
        }
        const product = await specApi.getProduct(created.id).catch(() => created);
        const parts = [`'${product.model}' 등록 완료 (원본: ${source.model}).`,
            `사양 값 ${values.length - failedValues.length}/${values.length}개, 부품 연결 ${links.length - failedLinks.length}/${links.length}개를 복사했습니다.`];
        if (failedValues.length) parts.push(`복사하지 못한 사양 값: ${failedValues.join(', ')}.`);
        if (failedLinks.length) parts.push(`연결하지 못한 부품: ${failedLinks.join(', ')}.`);
        parts.push('다른 값만 고치세요.');
        onDone({ product, message: parts.join(' ') });
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 p-4"
            onMouseDown={(e) => { if (e.target === e.currentTarget && !busy) onCancel(); }}>
            <form role="dialog" aria-modal="true" aria-label={`${source.model} 복사`}
                onSubmit={(e) => { e.preventDefault(); void run(); }}
                className="w-full max-w-[460px] rounded-2xl border border-divide bg-white p-5 shadow-xl">
                <h2 className="text-[16px] font-bold">‘{source.model}’ 복사</h2>
                <p className="mt-1 text-[12.5px] leading-5 text-muted">
                    제품 정보와 사양 값·부품 연결을 그대로 옮긴 새 모델을 만듭니다. 만든 뒤 다른 값만 고치면 됩니다.
                </p>

                <div className="mt-4 flex flex-col gap-3.5">
                    <Field label="새 모델명" htmlFor="copy-model" hint={duplicate ? '이미 있는 모델명입니다.' : trimmed === `${source.model}-` || !trimmed ? `'${source.model}-' 뒤에 붙일 이름을 입력하세요. 예: ${source.model}-GA70-PU03` : undefined}>
                        <input id="copy-model" ref={modelRef} value={model} onChange={(e) => setModel(e.target.value)} disabled={busy} maxLength={50} className={inputCls} />
                    </Field>
                    <Field label="제품 이름" htmlFor="copy-name">
                        <input id="copy-name" value={name} onChange={(e) => setName(e.target.value)} disabled={busy} maxLength={100} className={inputCls} />
                    </Field>
                    <fieldset>
                        <legend className="text-[12px] font-semibold text-ink">위치</legend>
                        <div className="mt-1.5 flex flex-col gap-1.5 text-[12.5px]">
                            <label className="inline-flex items-center gap-2">
                                <input type="radio" name="copy-placement" checked={placement === 'sibling'} onChange={() => setPlacement('sibling')}
                                    disabled={busy} className="accent-brand" />
                                {parentModel ? `원본과 같은 상위 모델(${parentModel}) 아래` : '원본과 같은 위치 (최상위 모델)'}
                            </label>
                            <label className="inline-flex items-center gap-2">
                                <input type="radio" name="copy-placement" checked={placement === 'child'} onChange={() => setPlacement('child')}
                                    disabled={busy} className="accent-brand" />
                                원본({source.model})의 하위 모델로
                            </label>
                        </div>
                    </fieldset>
                    <fieldset>
                        <legend className="text-[12px] font-semibold text-ink">복사할 것</legend>
                        <div className="mt-1.5 flex flex-col gap-1.5 text-[12.5px]">
                            <label className="inline-flex items-center gap-2">
                                <input type="checkbox" checked={copySpecs} onChange={(e) => setCopySpecs(e.target.checked)} disabled={busy || source.specs.length === 0} className="accent-brand" />
                                사양 값 {source.specs.length}개
                            </label>
                            <label className="inline-flex items-center gap-2">
                                <input type="checkbox" checked={copyLinks} onChange={(e) => setCopyLinks(e.target.checked)} disabled={busy || source.components.length === 0} className="accent-brand" />
                                부품 연결 {source.components.length}개
                            </label>
                        </div>
                    </fieldset>
                </div>

                {error && <div className="mt-3"><Notice kind="error">{error}</Notice></div>}
                {progress && <p role="status" className="mt-3 text-[12.5px] font-semibold text-brand-hover">{progress}</p>}

                <div className="mt-5 flex justify-end gap-2">
                    <button type="button" onClick={onCancel} disabled={busy} className={btnGhost}>취소</button>
                    <button type="submit" disabled={!canCopy} className={btnPrimary}>{busy ? '복사 중…' : '복사해서 만들기'}</button>
                </div>
            </form>
        </div>
    );
}
