import { useEffect, useRef, useState, type ClipboardEvent, type DragEvent } from 'react';
import { ApiError } from '../lib/http';
import { specApi, type DataType, type ImportBody, type ImportError, type ImportNewAttribute, type ImportPreview, type ImportSummary, type OwnerType, type SpecAttribute, type SpecMeta } from './api';
import { attributesFor, btnGhost, btnPrimary, btnTiny, errorMessage, inputCls, labelOf, selectCls, smallInputCls } from './styles';
import { Field, Notice, Pill } from './ui';

/**
 * 표 가져오기 탭.
 *
 * 입력 전: 대상 선택·양식 내려받기·붙여넣기/파일 영역을 가운데 폼으로 보여준다.
 * 미리보기 후: 입력 영역은 한 줄로 접고, 격자가 화면 전체 폭과 남은 높이를 쓴다.
 *   - 격자 안에서만 스크롤한다. 모델명 머리글은 위에, 속성 열은 왼쪽에 고정된다.
 *   - 도구줄(요약, 문제 행만 보기, 출처, 적용)은 격자 위에 항상 보인다.
 * 서버는 한 곳이라도 못 읽으면 아무것도 저장하지 않고 위치를 돌려준다. 그 칸을 빨갛게 표시한다.
 */

type RowMode = 'attribute' | 'new' | 'skip';

interface EditRow {
    label: string;
    mode: RowMode;
    attribute_key: string;
    newAttribute: ImportNewAttribute;
    cells: string[];
    match: 'key' | 'name' | 'alias' | null;
}

interface EditColumn {
    header: string;
    owner_id: string | null;
    owner_label: string | null;
    create: boolean;
    skip: boolean;
}

const OPTION_MARK = /\(?\s*(옵션|option|opt|선택)\s*\)?/i;

// 줄바꿈, 세미콜론, 공백이 붙은 슬래시만 구분자다. "MB/s", "N/A"처럼 붙은 슬래시는 그대로 둔다
const VALUE_SPLIT = /[\n;]|\s+\/\s*|\s*\/\s+/;
// 아직 모르는 값 표기. 서버(UNKNOWN_TOKENS)와 같다. 값으로 넣지 않고 건너뛴다
const UNKNOWN = new Set(['tbd', 'n/a', 'na', '?', '??', '-', '—', '–', '미정', '확인필요', '확인 필요', '추후', 'none']);

/** 서버(parser/spec_table.py split_cell)와 같은 규칙으로 셀을 나눠 미리 보여준다 */
function splitCell(raw: string): { value_text: string; is_option: boolean }[] {
    const parts = raw.split(VALUE_SPLIT).map((p) => (p ?? '').trim()).filter(Boolean);
    const explicit = parts.some((p) => OPTION_MARK.test(p));
    const out: { value_text: string; is_option: boolean }[] = [];
    parts.forEach((part, i) => {
        const marked = OPTION_MARK.test(part);
        const text = part.replace(OPTION_MARK, '').replace(/^[\s-]+|[\s-]+$/g, '');
        if (!text || UNKNOWN.has(text.toLowerCase())) return;
        out.push({ value_text: text, is_option: explicit ? marked : i > 0 });
    });
    return out;
}

function hint(dataType: DataType | undefined, text: string): string | null {
    if (dataType === 'number' && !/-?\d/.test(text.replace(/,/g, ''))) return '숫자가 없습니다';
    if (dataType === 'bool' && !/^(1|0|true|false|yes|no|y|n|o|x|예|아니오|아니요|있음|없음|지원|미지원|가능|불가|포함|제외)$/i.test(text)) return '예/아니오로 적어 주세요';
    return null;
}

function toRows(preview: ImportPreview): EditRow[] {
    return preview.rows.map((r) => ({
        label: r.label,
        mode: r.attribute_key ? 'attribute' : 'skip',
        attribute_key: r.attribute_key ?? '',
        newAttribute: { key: '', name: r.label, category: 'other', data_type: 'text', unit: '', description: '' },
        cells: r.cells.map((c) => c.raw),
        match: r.match,
    }));
}

const KEY_RE = /^[a-z][a-z0-9_]{1,49}$/;

/**
 * 작성 중인 가져오기 초안. 새로고침하거나 다른 탭·화면으로 갔다 와도 그대로 복원한다.
 * 파일(File 객체)은 저장할 수 없어서 붙여넣은 표와 미리보기 격자(수정 내용 포함)만 남긴다.
 * 적용이 끝나거나 "처음으로"를 누르면 지운다.
 */
const DRAFT_KEY = 'spec-import-draft-v1';

interface Draft {
    savedAt: string;
    ownerType: OwnerType;
    kind: string;
    text: string;
    columns: EditColumn[] | null;
    rows: EditRow[];
    source: string;
    skippedColumns: string[];
    replace: boolean;
    sourceNote: string;
}

function loadDraft(): Draft | null {
    try {
        const raw = window.localStorage.getItem(DRAFT_KEY);
        if (!raw) return null;
        const draft = JSON.parse(raw) as Draft;
        if (!draft || typeof draft !== 'object' || !Array.isArray(draft.rows)) return null;
        return draft;
    } catch {
        return null;
    }
}

function saveDraft(draft: Draft) {
    try {
        window.localStorage.setItem(DRAFT_KEY, JSON.stringify(draft));
    } catch {
        /* 저장 공간이 꽉 찼거나 비공개 모드면 복원 없이 동작한다 */
    }
}

function clearDraft() {
    try {
        window.localStorage.removeItem(DRAFT_KEY);
    } catch {
        /* 무시 */
    }
}

function agoText(iso: string): string {
    const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (minutes < 1) return '방금';
    if (minutes < 60) return `${minutes}분 전`;
    const hours = Math.round(minutes / 60);
    return hours < 24 ? `${hours}시간 전` : `${Math.round(hours / 24)}일 전`;
}

export function ImportTab({
    meta,
    attributes,
    onImported,
    onOpenTab,
}: {
    meta: SpecMeta | null;
    attributes: SpecAttribute[];
    onImported: (ownerType: OwnerType) => Promise<void>;
    onOpenTab: (tab: 'products' | 'components' | 'attributes') => void;
}) {
    // 마운트 때 한 번만 읽는다. 있으면 그 값으로 시작하고 복원 안내를 띄운다
    const [draft] = useState<Draft | null>(loadDraft);
    const [restoredAt, setRestoredAt] = useState<string | null>(draft?.columns ? draft.savedAt : null);
    const [ownerType, setOwnerType] = useState<OwnerType>(draft?.ownerType ?? 'product');
    const [kind, setKind] = useState(draft?.kind ?? 'cpu');
    const [text, setText] = useState(draft?.text ?? '');
    const [file, setFile] = useState<File | null>(null);
    /** 붙여넣거나 올린 화면 캡처와 썸네일 URL. 서버의 VLM OCR이 표로 읽는다. 파일과 마찬가지로 저장(복원)은 안 된다 */
    const [image, setImage] = useState<{ file: File; url: string } | null>(null);
    const [columns, setColumns] = useState<EditColumn[] | null>(draft?.columns ?? null);
    const [rows, setRows] = useState<EditRow[]>(draft?.rows ?? []);
    const [source, setSource] = useState(draft?.source ?? '');
    const [skippedColumns, setSkippedColumns] = useState<string[]>(draft?.skippedColumns ?? []);
    const [replace, setReplace] = useState(draft?.replace ?? true);
    const [sourceNote, setSourceNote] = useState(draft?.sourceNote ?? '');
    const [busy, setBusy] = useState<'parse' | 'apply' | null>(null);
    const [error, setError] = useState('');
    const [cellErrors, setCellErrors] = useState<Map<string, string>>(new Map());
    const [result, setResult] = useState<ImportSummary | null>(null);
    const [showAll, setShowAll] = useState(false);
    const [problemsOnly, setProblemsOnly] = useState(false);
    const [inputOpen, setInputOpen] = useState(false);
    const fileRef = useRef<HTMLInputElement>(null);

    // 입력이나 격자가 바뀔 때마다 저장한다 (외부 저장소 동기화라 효과로 둔다). 비어 있으면 지운다
    useEffect(() => {
        if (result) return; // 적용이 끝난 뒤에는 남기지 않는다
        if (!columns && !text.trim()) {
            clearDraft();
            return;
        }
        saveDraft({ savedAt: new Date().toISOString(), ownerType, kind, text, columns, rows, source, skippedColumns, replace, sourceNote });
    }, [result, ownerType, kind, text, columns, rows, source, skippedColumns, replace, sourceNote]);

    // 썸네일 object URL은 이미지가 바뀌거나 화면을 떠날 때 해제한다 (정리만 하는 효과)
    useEffect(() => () => { if (image) URL.revokeObjectURL(image.url); }, [image]);

    const pickImage = (candidate: File | null | undefined) => {
        if (!candidate || !candidate.type.startsWith('image/')) return false;
        const named = candidate.name && candidate.name !== 'image.png'
            ? candidate
            : new File([candidate], `capture-${Date.now()}.${(candidate.type.split('/')[1] || 'png').replace('jpeg', 'jpg')}`, { type: candidate.type });
        setImage({ file: named, url: URL.createObjectURL(named) });
        setError('');
        return true;
    };

    /** 입력 폼 어디서든 Ctrl+V로 캡처를 붙여넣을 수 있다. 텍스트 붙여넣기는 그대로 둔다 */
    const onPaste = (e: ClipboardEvent<HTMLElement>) => {
        const item = [...(e.clipboardData?.items ?? [])].find((i) => i.kind === 'file' && i.type.startsWith('image/'));
        if (!item) return;
        if (pickImage(item.getAsFile())) e.preventDefault();
    };

    const onDrop = (e: DragEvent<HTMLElement>) => {
        const dropped = e.dataTransfer?.files?.[0];
        if (!dropped) return;
        e.preventDefault();
        if (dropped.type.startsWith('image/')) pickImage(dropped);
        else if (/\.xlsx$/i.test(dropped.name)) { setFile(dropped); setError(''); }
        else setError('엑셀(.xlsx)이나 이미지만 올릴 수 있습니다.');
    };

    const attributeOf = (key: string) => attributes.find((a) => a.key === key);
    const categories = Object.keys(meta?.attribute_categories ?? {});
    const categoryOrder = (c: string) => { const i = categories.indexOf(c); return i < 0 ? 99 : i; };
    const effectiveKind = ownerType === 'component' ? kind : null;
    // 속성 선택 목록은 대상(제품 또는 부품 종류)에 맞는 것만. 행에 이미 맞춰진 속성은 목록에 없어도 그대로 둔다
    const scopedAttributes = showAll ? attributes : attributesFor(attributes, effectiveKind);
    const hiddenCount = attributes.length - scopedAttributes.length;
    const attributeGroups = new Map<string, SpecAttribute[]>();
    for (const a of scopedAttributes) attributeGroups.set(a.category, [...(attributeGroups.get(a.category) ?? []), a]);

    const hasInput = Boolean(text.trim()) || Boolean(file) || Boolean(image);

    async function parse() {
        if (!hasInput) return;
        setBusy('parse');
        setError('');
        setResult(null);
        setCellErrors(new Map());
        try {
            // 이미지 > 엑셀 > 붙여넣기 순으로 하나만 읽는다
            const upload = image?.file ?? file;
            const preview = await specApi.parseImport({ owner_type: ownerType, kind: effectiveKind, text: upload ? undefined : text.trim() || undefined, file: upload });
            setColumns(preview.columns.map((c) => ({ header: c.header, owner_id: c.owner_id, owner_label: c.owner_label, create: true, skip: false })));
            setRows(toRows(preview));
            setSource(preview.source);
            setSkippedColumns(preview.skipped_columns);
            setProblemsOnly(false);
            setInputOpen(false);
            setRestoredAt(null);
            if (image && preview.recognized_text) {
                // VLM이 읽은 표를 붙여넣기 칸에 넣어 두면 고쳐서 다시 읽을 수 있고, 새로고침해도 남는다
                setText(preview.recognized_text);
                setImage(null);
            }
        } catch (e) {
            setError(errorMessage(e, '표를 읽지 못했습니다.'));
        } finally {
            setBusy(null);
        }
    }

    async function apply() {
        if (!columns) return;
        setBusy('apply');
        setError('');
        setCellErrors(new Map());
        const body: ImportBody = {
            owner_type: ownerType,
            kind: effectiveKind,
            replace,
            source_note: sourceNote.trim(),
            source_page: null,
            columns: columns.map((c) => ({ header: c.header, owner_id: c.owner_id, create: c.create, skip: c.skip })),
            rows: rows.map((r) => ({
                attribute_key: r.mode === 'attribute' ? r.attribute_key || null : null,
                new_attribute: r.mode === 'new' ? { ...r.newAttribute, key: r.newAttribute.key.trim().toLowerCase() } : null,
                cells: r.cells,
            })),
        };
        try {
            const summary = await specApi.applyImport(body);
            setResult(summary);
            clearDraft();
            setRestoredAt(null);
            await onImported(ownerType);
        } catch (e) {
            const detail = e instanceof ApiError ? (e.detail as { errors?: ImportError[] } | undefined) : undefined;
            if (detail?.errors?.length) {
                const next = new Map<string, string>();
                for (const err of detail.errors) next.set(`${err.row ?? '-'}:${err.column ?? '-'}`, err.message);
                setCellErrors(next);
                setProblemsOnly(true);
                setError(`${detail.errors.length}곳을 고쳐야 합니다. 문제 있는 행만 보여줍니다. 아무것도 저장하지 않았습니다.`);
            } else {
                setError(errorMessage(e, '저장하지 못했습니다.'));
            }
        } finally {
            setBusy(null);
        }
    }

    const updateRow = (i: number, patch: Partial<EditRow>) => setRows((list) => list.map((r, x) => (x === i ? { ...r, ...patch } : r)));
    const updateColumn = (i: number, patch: Partial<EditColumn>) => setColumns((list) => (list ?? []).map((c, x) => (x === i ? { ...c, ...patch } : c)));

    /** 행의 자료형: 선택한 속성 또는 새 속성의 자료형 */
    const rowDataType = (r: EditRow): DataType | undefined =>
        r.mode === 'new' ? r.newAttribute.data_type : r.mode === 'attribute' ? attributeOf(r.attribute_key)?.data_type : undefined;

    /** 행에 고칠 곳이 있는지: 속성 못 맞춤, 새 속성 키 불량, 값 힌트, 서버 오류 */
    const rowHasProblem = (r: EditRow, ri: number): boolean => {
        if (r.mode === 'skip') return true;
        if (r.mode === 'new' && !KEY_RE.test(r.newAttribute.key.trim().toLowerCase())) return true;
        if (cellErrors.has(`${ri}:-`)) return true;
        const dataType = rowDataType(r);
        return r.cells.some((raw, ci) => {
            if (cellErrors.has(`${ri}:${ci}`)) return true;
            if (columns?.[ci]?.skip) return false;
            return splitCell(raw).some((v) => hint(dataType, v.value_text) !== null);
        });
    };

    const activeRows = rows.filter((r) => r.mode !== 'skip' && (r.mode === 'new' || r.attribute_key));
    const activeColumns = (columns ?? []).filter((c) => !c.skip);
    const problemRows = rows.map((r, ri) => (rowHasProblem(r, ri) ? ri : -1)).filter((i) => i >= 0);
    const unmatched = rows.filter((r) => r.mode === 'skip').length;
    const visibleRows = problemsOnly ? problemRows : rows.map((_, i) => i);
    const canApply = busy === null && activeRows.length > 0 && activeColumns.length > 0
        && rows.every((r) => r.mode !== 'new' || KEY_RE.test(r.newAttribute.key.trim().toLowerCase()));

    const resetPreview = () => { setColumns(null); setRows([]); setResult(null); setError(''); setCellErrors(new Map()); setInputOpen(false); setRestoredAt(null); };
    const discardAll = () => { resetPreview(); setText(''); setFile(null); setImage(null); if (fileRef.current) fileRef.current.value = ''; clearDraft(); };

    const targetLabel = ownerType === 'product' ? '제품' : `부품 · ${labelOf(meta?.component_kinds, kind)}`;

    // ---------- 입력 폼 (미리보기 전, 또는 "입력 바꾸기"로 다시 연 상태) ----------
    const inputForm = (
        <div className="flex flex-col gap-4">
            <section className="rounded-2xl border border-divide bg-white px-5 py-4">
                <div className="flex flex-wrap items-end gap-3">
                    <Field label="대상" htmlFor="import-owner">
                        <select id="import-owner" value={ownerType} onChange={(e) => { setOwnerType(e.target.value as OwnerType); resetPreview(); }} className={`${selectCls} w-[160px]`}>
                            <option value="product">제품</option>
                            <option value="component">부품</option>
                        </select>
                    </Field>
                    {ownerType === 'component' && (
                        <Field label="부품 종류" htmlFor="import-kind">
                            <select id="import-kind" value={kind} onChange={(e) => { setKind(e.target.value); resetPreview(); }} className={`${selectCls} w-[160px]`}>
                                {Object.entries(meta?.component_kinds ?? { cpu: 'CPU' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                            </select>
                        </Field>
                    )}
                    <a href={specApi.templateUrl(ownerType, effectiveKind)} download className={btnGhost}>엑셀 양식 내려받기</a>
                    <span className="text-[11.5px] text-muted">양식에는 현재 속성과 등록된 {ownerType === 'product' ? '제품' : '부품'}의 값이 채워져 있습니다. 고쳐서 다시 올리면 됩니다.</span>
                </div>
            </section>

            <section
                className="rounded-2xl border border-divide bg-white px-5 py-4"
                onPaste={onPaste}
                onDrop={onDrop}
                onDragOver={(e) => e.preventDefault()}
            >
                <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px] gap-4">
                    <Field label="표 붙여넣기 또는 화면 캡처 붙여넣기" htmlFor="import-text" hint="엑셀 범위를 복사해 붙여넣거나(탭 구분), 마크다운 표·CSV도 됩니다. 캡처 이미지를 Ctrl+V로 붙여넣으면 VLM이 표를 읽어 줍니다. 첫 행은 머리글(모델명), 첫 열은 속성입니다.">
                        <textarea
                            id="import-text"
                            value={text}
                            onChange={(e) => setText(e.target.value)}
                            rows={9}
                            placeholder={'항목\tN5800\tA650\n메모리\t16GB\t16 / 32(옵션)\n무게\t1.75kg\t2.16kg'}
                            className={`${inputCls} h-auto py-2 font-mono text-[12px] leading-5 whitespace-pre`}
                            spellCheck={false}
                        />
                    </Field>
                    <div className="flex flex-col gap-3">
                        <Field label="또는 파일" hint="엑셀(.xlsx) 또는 캡처 이미지(PNG, JPG). 끌어다 놓아도 됩니다.">
                            <input
                                ref={fileRef}
                                type="file"
                                accept=".xlsx,image/*"
                                onChange={(e) => {
                                    const picked = e.target.files?.[0] ?? null;
                                    if (picked && picked.type.startsWith('image/')) { pickImage(picked); setFile(null); }
                                    else setFile(picked);
                                }}
                                className="block w-full text-[12px] text-muted file:mr-3 file:h-9 file:rounded-lg file:border file:border-line file:bg-white file:px-3 file:text-[12px] file:font-semibold file:text-ink hover:file:bg-chip"
                            />
                            {file && (
                                <p className="mt-1.5 flex items-center gap-2 text-[12px]">
                                    <span className="truncate">{file.name}</span>
                                    <button type="button" onClick={() => { setFile(null); if (fileRef.current) fileRef.current.value = ''; }} className={btnTiny}>제거</button>
                                </p>
                            )}
                        </Field>

                        <div
                            className={`rounded-xl border border-dashed px-3 py-3 text-[12px] ${image ? 'border-brand/40 bg-brand-tint' : 'border-line bg-surface text-muted'}`}
                            aria-label="화면 캡처"
                        >
                            {image ? (
                                <div className="flex items-start gap-3">
                                    <img src={image.url} alt="붙여넣은 화면 캡처" className="max-h-[120px] max-w-[160px] rounded-lg border border-line object-contain bg-white" />
                                    <div className="min-w-0 flex-1">
                                        <p className="font-semibold text-ink truncate">{image.file.name}</p>
                                        <p className="mt-0.5 text-muted">{(image.file.size / 1024).toFixed(0)}KB · VLM이 표를 읽습니다. 숫자가 틀릴 수 있으니 미리보기에서 확인하세요.</p>
                                        <button type="button" onClick={() => setImage(null)} className={`${btnTiny} mt-1 -ml-2`}>제거</button>
                                    </div>
                                </div>
                            ) : (
                                <p>화면 캡처를 여기나 왼쪽 칸에 <kbd className="rounded border border-line bg-white px-1 py-0.5 text-[11px] font-mono text-ink">Ctrl</kbd>+<kbd className="rounded border border-line bg-white px-1 py-0.5 text-[11px] font-mono text-ink">V</kbd>로 붙여넣으세요.</p>
                            )}
                        </div>

                        <button type="button" onClick={() => void parse()} disabled={busy !== null || !hasInput} className={`${btnPrimary} w-full justify-center`}>
                            {busy === 'parse' ? (image ? 'VLM이 표를 읽는 중…' : '읽는 중…') : image ? '캡처에서 미리보기 만들기' : '미리보기 만들기'}
                        </button>
                        {(image || file) && text.trim() && <p className="text-[11.5px] text-warn">{image ? '캡처 이미지' : '파일'}와 붙여넣은 표가 둘 다 있으면 {image ? '이미지' : '파일'}를 먼저 읽습니다.</p>}
                    </div>
                </div>
            </section>
        </div>
    );

    if (!columns) {
        return (
            <main className="flex-1 min-w-0 min-h-0 md:overflow-y-auto bg-surface px-4 py-6 sm:p-8">
                <div className="mx-auto max-w-[1100px] flex flex-col gap-5">
                    <div>
                        <h1 className="text-[22px] font-bold tracking-tight">표 가져오기</h1>
                        <p className="mt-1.5 text-[12.5px] leading-6 text-muted max-w-[760px]">
                            속성이 행, 모델이 열인 표를 넣으면 속성 이름을 자동으로 맞추고 값을 나눕니다. 틀린 곳만 고치고 적용하세요.
                            값이 여러 개면 " / "(공백 있는 슬래시)나 줄바꿈으로 나누고, 두 번째 값부터는 옵션 구성입니다. "(옵션)"을 붙여 직접 표시해도 됩니다.
                            TBD, N/A, ? 같은 미정 표기는 건너뛰고, "MB/s"처럼 붙은 슬래시는 나누지 않습니다.
                        </p>
                    </div>
                    {error && <Notice kind="error">{error}</Notice>}
                    {draft?.text && !draft.columns && text === draft.text && (
                        <Notice kind="ok">
                            {agoText(draft.savedAt)} 붙여넣은 표를 복원했습니다.
                            <button type="button" onClick={discardAll} className={`${btnTiny} ml-1 text-danger`}>지우기</button>
                        </Notice>
                    )}
                    {inputForm}
                </div>
            </main>
        );
    }

    // ---------- 미리보기 격자 (전체 폭, 남은 높이, 머리글·속성 열 고정) ----------
    return (
        <main className="flex-1 min-w-0 min-h-0 flex flex-col bg-surface">
            {/* 접힌 입력 줄 */}
            <div className="shrink-0 border-b border-divide bg-white px-4 sm:px-6 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px]">
                <span className="font-bold">표 가져오기</span>
                <span className="text-muted">{targetLabel} · {source} · 행 {rows.length} · 열 {columns.length}{skippedColumns.length > 0 && ` · 건너뛴 보조 열 ${skippedColumns.join(', ')}`}</span>
                <div className="ml-auto flex items-center gap-2">
                    <button type="button" onClick={() => setInputOpen((v) => !v)} className={btnTiny}>{inputOpen ? '입력 닫기' : '입력 바꾸기'}</button>
                    <button type="button" onClick={() => void parse()} disabled={busy !== null || !hasInput} className={btnTiny} title="같은 입력으로 미리보기를 다시 만듭니다 (고친 내용은 사라집니다)">다시 읽기</button>
                    <button type="button" onClick={() => { if (window.confirm('작성 중인 미리보기와 붙여넣은 표를 지우고 처음으로 돌아갈까요?')) discardAll(); }} className={btnTiny}>처음으로</button>
                </div>
            </div>
            {inputOpen && (
                <div className="shrink-0 border-b border-divide bg-surface px-4 sm:px-6 py-4 max-h-[50vh] overflow-y-auto">
                    <div className="mx-auto max-w-[1100px]">{inputForm}</div>
                </div>
            )}

            {/* 도구줄: 항상 보인다 */}
            <div className="shrink-0 border-b border-divide bg-white px-4 sm:px-6 py-2.5 flex flex-wrap items-center gap-x-4 gap-y-2 text-[12.5px]">
                <div className="flex items-center gap-2">
                    <Pill tone="brand">맞춤 {rows.length - unmatched}</Pill>
                    {unmatched > 0 && <Pill tone="warn">속성 못 맞춤 {unmatched}</Pill>}
                    {problemRows.length > 0
                        ? <span className="text-danger font-semibold">고칠 곳 {problemRows.length}행</span>
                        : <span className="text-muted">고칠 곳 없음</span>}
                </div>
                <label className={`inline-flex items-center gap-1.5 ${problemRows.length === 0 ? 'text-muted/60' : ''}`}>
                    <input type="checkbox" checked={problemsOnly} onChange={(e) => setProblemsOnly(e.target.checked)} disabled={problemRows.length === 0} className="accent-brand" />
                    문제 있는 행만 보기
                </label>
                {(hiddenCount > 0 || showAll) && (
                    <label className="inline-flex items-center gap-1.5 text-muted" title="기본은 선택한 대상에 맞는 속성만 보여줍니다">
                        <input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} className="accent-brand" />
                        속성 목록에 모든 속성 보기{!showAll && ` (+${hiddenCount})`}
                    </label>
                )}
                <div className="ml-auto flex flex-wrap items-center gap-3">
                    <input value={sourceNote} onChange={(e) => setSourceNote(e.target.value)} placeholder="출처 메모 (예: R&D 2026-11)" aria-label="출처 메모" className={`${smallInputCls} w-[200px]`} />
                    <label className="inline-flex items-center gap-1.5" title="끄면 표에 없는 값만 더하고 기존 값은 그대로 둡니다">
                        <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} className="accent-brand" />
                        기존 값 교체
                    </label>
                    <button type="button" onClick={() => void apply()} disabled={!canApply} className={btnPrimary}>
                        {busy === 'apply' ? '저장 중…' : `적용 (${activeRows.length}행 × ${activeColumns.length}열)`}
                    </button>
                </div>
            </div>

            {(error || result || restoredAt) && (
                <div className="shrink-0 px-4 sm:px-6 py-2 flex flex-col gap-2">
                    {restoredAt && (
                        <Notice kind="ok">
                            {agoText(restoredAt)} 작성하던 미리보기를 복원했습니다. 고친 내용도 그대로입니다. 이어서 작업하거나{' '}
                            <button type="button" onClick={discardAll} className={`${btnTiny} ml-1 text-danger`}>버리고 새로 시작</button>
                        </Notice>
                    )}
                    {error && <Notice kind="error">{error}</Notice>}
                    {result && (
                        <Notice kind="ok">
                            적용했습니다. {ownerType === 'product' ? '제품' : '부품'} {result.owners_created}개 새로 등록, 속성 {result.attributes_created}개 추가,
                            값 {result.values_added}건 저장(기존 값 {result.values_replaced}건 교체), 건너뛴 행 {result.rows_skipped}개.
                            <button type="button" onClick={() => onOpenTab(ownerType === 'product' ? 'products' : 'components')} className={`${btnTiny} ml-2 text-brand`}>
                                {ownerType === 'product' ? '제품 탭에서 확인' : '부품 탭에서 확인'}
                            </button>
                        </Notice>
                    )}
                </div>
            )}

            {/* 격자: 이 영역 안에서만 스크롤. 머리글은 위, 속성 열은 왼쪽에 고정 */}
            <div className="flex-1 min-h-0 max-h-[70vh] md:max-h-none overflow-auto bg-white">
                <table className="min-w-full border-separate border-spacing-0 text-[12px]">
                    <thead>
                        <tr className="align-top">
                            <th className="sticky top-0 left-0 z-30 bg-surface border-b border-r border-divide px-4 py-2.5 text-left font-semibold text-muted min-w-[280px] w-[280px]">
                                속성 <span className="font-normal">(표의 행 이름 → 사전 속성)</span>
                            </th>
                            {columns.map((c, ci) => (
                                <th key={ci} className={`sticky top-0 z-20 bg-surface border-b border-divide px-3 py-2.5 text-left min-w-[200px] ${c.skip ? 'opacity-40' : ''}`}>
                                    <div className="flex items-center gap-1.5">
                                        <span className="font-bold truncate" title={c.header}>{c.header}</span>
                                        {c.owner_id ? <Pill tone="brand">기존</Pill> : c.create ? <Pill tone="warn">새로 등록</Pill> : <Pill>미등록</Pill>}
                                    </div>
                                    {c.owner_label && c.owner_label !== c.header && <div className="mt-0.5 text-[11px] font-normal text-muted truncate">{c.owner_label}</div>}
                                    <div className="mt-1 flex items-center gap-2 text-[11px] font-normal text-muted">
                                        {!c.owner_id && (
                                            <label className="inline-flex items-center gap-1">
                                                <input type="checkbox" checked={c.create} onChange={(e) => updateColumn(ci, { create: e.target.checked })} className="accent-brand" />
                                                없으면 등록
                                            </label>
                                        )}
                                        <label className="inline-flex items-center gap-1">
                                            <input type="checkbox" checked={c.skip} onChange={(e) => updateColumn(ci, { skip: e.target.checked })} className="accent-brand" />
                                            건너뛰기
                                        </label>
                                    </div>
                                    {cellErrors.get(`-:${ci}`) && <div className="mt-1 text-[11px] font-normal text-danger">{cellErrors.get(`-:${ci}`)}</div>}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {visibleRows.length === 0 && (
                            <tr>
                                <td colSpan={columns.length + 1} className="px-4 py-8 text-center text-[12.5px] text-muted">고칠 곳이 없습니다. 적용을 누르세요.</td>
                            </tr>
                        )}
                        {visibleRows.map((ri) => {
                            const r = rows[ri];
                            const attribute = r.mode === 'attribute' ? attributeOf(r.attribute_key) : undefined;
                            const dataType = rowDataType(r);
                            const rowError = cellErrors.get(`${ri}:-`);
                            const problem = rowHasProblem(r, ri);
                            return (
                                <tr key={ri} className={`align-top ${r.mode === 'skip' ? 'bg-warn-soft/30' : ''}`}>
                                    <td className={`sticky left-0 z-10 border-b border-r border-divide px-4 py-2 min-w-[280px] w-[280px] ${r.mode === 'skip' ? 'bg-[#FFFBEF]' : 'bg-white'}`}>
                                        <div className="flex items-center gap-1.5">
                                            {problem && <span aria-hidden className="w-1.5 h-1.5 rounded-full bg-danger shrink-0" />}
                                            <span className="font-semibold truncate" title={r.label}>{r.label}</span>
                                            {r.mode === 'attribute' && r.match && r.match !== 'key' && <Pill>{r.match === 'name' ? '이름 일치' : '별칭 일치'}</Pill>}
                                        </div>
                                        <select
                                            value={r.mode === 'skip' ? '' : r.mode === 'new' ? '__new__' : r.attribute_key}
                                            onChange={(e) => {
                                                const v = e.target.value;
                                                updateRow(ri, v === '' ? { mode: 'skip' } : v === '__new__' ? { mode: 'new' } : { mode: 'attribute', attribute_key: v });
                                            }}
                                            aria-label={`${r.label} 속성`}
                                            className={`${smallInputCls} mt-1.5 ${r.mode === 'skip' ? 'border-warn text-warn' : ''}`}
                                        >
                                            <option value="">건너뛰기 (속성 없음)</option>
                                            <option value="__new__">+ 새 속성으로 만들기</option>
                                            {[...attributeGroups.entries()].sort((a, b) => categoryOrder(a[0]) - categoryOrder(b[0])).map(([category, list]) => (
                                                <optgroup key={category} label={labelOf(meta?.attribute_categories, category)}>
                                                    {list.map((a) => <option key={a.key} value={a.key}>{a.name}{a.unit ? ` (${a.unit})` : ''}</option>)}
                                                </optgroup>
                                            ))}
                                            {r.mode === 'attribute' && attribute && !scopedAttributes.some((a) => a.key === attribute.key) && (
                                                <optgroup label="다른 대상의 속성">
                                                    <option value={attribute.key}>{attribute.name}{attribute.unit ? ` (${attribute.unit})` : ''}</option>
                                                </optgroup>
                                            )}
                                        </select>
                                        {r.mode === 'new' && (
                                            <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                                                <input value={r.newAttribute.key} onChange={(e) => updateRow(ri, { newAttribute: { ...r.newAttribute, key: e.target.value } })} placeholder="키 (예: fan_count)" aria-label="새 속성 키" className={`${smallInputCls} font-mono col-span-2 ${KEY_RE.test(r.newAttribute.key.trim().toLowerCase()) ? '' : 'border-danger'}`} />
                                                <input value={r.newAttribute.name} onChange={(e) => updateRow(ri, { newAttribute: { ...r.newAttribute, name: e.target.value } })} placeholder="이름" aria-label="새 속성 이름" className={`${smallInputCls} col-span-2`} />
                                                <select value={r.newAttribute.category} onChange={(e) => updateRow(ri, { newAttribute: { ...r.newAttribute, category: e.target.value } })} aria-label="분류" className={smallInputCls}>
                                                    {Object.entries(meta?.attribute_categories ?? { other: '기타' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                                </select>
                                                <select value={r.newAttribute.data_type} onChange={(e) => updateRow(ri, { newAttribute: { ...r.newAttribute, data_type: e.target.value as DataType } })} aria-label="자료형" className={smallInputCls}>
                                                    {Object.entries(meta?.data_types ?? { text: '텍스트' }).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                                                </select>
                                                <input value={r.newAttribute.unit} onChange={(e) => updateRow(ri, { newAttribute: { ...r.newAttribute, unit: e.target.value } })} placeholder="단위" aria-label="단위" className={`${smallInputCls} col-span-2`} />
                                            </div>
                                        )}
                                        {rowError && <p className="mt-1 text-[11px] text-danger">{rowError}</p>}
                                    </td>
                                    {r.cells.map((raw, ci) => {
                                        const column = columns[ci];
                                        const values = splitCell(raw);
                                        const serverError = cellErrors.get(`${ri}:${ci}`);
                                        const hints = r.mode === 'skip' || column?.skip ? [] : values.map((v) => hint(dataType, v.value_text)).filter(Boolean);
                                        const bad = Boolean(serverError) || hints.length > 0;
                                        return (
                                            <td key={ci} className={`border-b border-divide px-3 py-2 ${column?.skip || r.mode === 'skip' ? 'opacity-40' : ''}`}>
                                                <textarea
                                                    value={raw}
                                                    onChange={(e) => updateRow(ri, { cells: r.cells.map((c, x) => (x === ci ? e.target.value : c)) })}
                                                    rows={Math.min(4, Math.max(1, raw.split('\n').length))}
                                                    aria-label={`${r.label} ${column?.header}`}
                                                    className={`${smallInputCls} h-auto py-1.5 resize-y leading-5 ${bad ? 'border-danger bg-danger-surface' : ''}`}
                                                />
                                                {values.length > 0 && (
                                                    <div className="mt-1 flex flex-wrap gap-1">
                                                        {values.map((v, x) => (
                                                            <span key={x} className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10.5px] ${v.is_option ? 'bg-warn-soft text-warn' : 'bg-chip text-muted'}`}>
                                                                {v.value_text}{v.is_option && ' · 옵션'}
                                                            </span>
                                                        ))}
                                                    </div>
                                                )}
                                                {serverError ? <p className="mt-1 text-[11px] text-danger">{serverError}</p>
                                                    : hints.length > 0 && <p className="mt-1 text-[11px] text-danger">{hints[0]}</p>}
                                            </td>
                                        );
                                    })}
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </main>
    );
}
