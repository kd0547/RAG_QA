import { useState, type FormEvent } from 'react';

import { FolderIcon } from '../components/icons';
import type { FileGroup } from './types';

const dateFormat = new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: 'Asia/Seoul',
});

function formatGroupDate(value?: string): string {
    if (!value) return '—';
    const iso = value.replace(' ', 'T');
    const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(iso);
    const date = new Date(hasTimezone ? iso : `${iso}Z`);
    return Number.isNaN(date.getTime()) ? '—' : dateFormat.format(date);
}

export function GroupInfoSidebar({ group, onSaveDescription }: { group: FileGroup; onSaveDescription: (description: string) => Promise<void> }) {
    const [editing, setEditing] = useState(false);
    const [draft, setDraft] = useState('');
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    const [saved, setSaved] = useState(false);

    const save = async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const description = draft.trim();
        if (description === group.description) {
            setEditing(false);
            return;
        }
        setSaving(true);
        setError('');
        setSaved(false);
        try {
            await onSaveDescription(description);
            setEditing(false);
            setSaved(true);
        } catch (cause) {
            setError(cause instanceof Error ? cause.message : '설명을 저장하지 못했습니다. 다시 시도해 주세요.');
        } finally {
            setSaving(false);
        }
    };

    return (
        <aside aria-labelledby="group-info-title" className="mb-5 rounded-2xl border border-line bg-surface p-4 lg:sticky lg:top-6 lg:mb-0">
            <div className="flex items-center gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-pale text-brand"><FolderIcon /></span>
                <h2 id="group-info-title" className="text-[12px] font-bold text-ink/70">문서 그룹 정보</h2>
            </div>

            <h3 className="mt-4 break-words text-[16px] font-bold leading-relaxed text-ink">{group.name}</h3>
            <div className="mt-4 border-t border-divide pt-4">
                <div className="flex items-center justify-between gap-2">
                    <h4 className="text-[12px] font-bold text-ink">그룹 설명</h4>
                    {!editing && (
                        <button
                            type="button"
                            onClick={() => { setDraft(group.description); setError(''); setSaved(false); setEditing(true); }}
                            className="text-[11.5px] font-bold text-brand-hover hover:underline focus-visible:outline-2 focus-visible:outline-brand"
                        >
                            {group.description ? '수정' : '추가'}
                        </button>
                    )}
                </div>
                {editing ? (
                    <form onSubmit={(event) => void save(event)} onKeyDown={(event) => { if (event.key === 'Escape' && !saving) setEditing(false); }} className="mt-2">
                        <textarea
                            value={draft}
                            onChange={(event) => setDraft(event.target.value)}
                            disabled={saving}
                            autoFocus
                            rows={5}
                            maxLength={500}
                            aria-label={`${group.name} 그룹 설명`}
                            placeholder="예: KC 안전확인·적합등록 인증서와 시험 자료"
                            className="w-full resize-y rounded-lg border border-line bg-white px-2.5 py-2 text-[12px] leading-relaxed text-ink focus:outline-none focus:border-brand disabled:opacity-50"
                        />
                        {error && <p role="alert" className="mt-2 break-words text-[11.5px] text-danger">{error}</p>}
                        <div className="mt-2 flex justify-end gap-2">
                            <button type="button" onClick={() => setEditing(false)} disabled={saving} className="h-8 rounded-lg px-2 text-[11.5px] font-semibold text-ink/70 hover:bg-white disabled:opacity-50">취소</button>
                            <button type="submit" disabled={saving} className="h-8 rounded-lg bg-brand px-3 text-[11.5px] font-bold text-white hover:bg-brand-hover disabled:opacity-50">{saving ? '저장 중…' : '저장'}</button>
                        </div>
                    </form>
                ) : (
                    <p className="mt-2 break-words text-[12px] leading-relaxed text-ink/70">{group.description || '아직 설명이 없습니다. 이 그룹에 모을 문서를 적어 주세요.'}</p>
                )}
                <p className="mt-2 text-[11.5px] leading-relaxed text-ink/60">AI가 관련 문서를 찾을 때 참고합니다.</p>
                {saved && <p role="status" className="mt-2 text-[11.5px] text-brand-hover">그룹 설명을 저장했습니다.</p>}
            </div>

            <dl className="mt-5 divide-y divide-divide border-t border-divide text-[12px]">
                <div className="flex items-center justify-between gap-3 py-3">
                    <dt className="text-ink/70">등록된 파일</dt>
                    <dd className="font-semibold tabular-nums text-ink">{group.file_count.toLocaleString('ko-KR')}개</dd>
                </div>
                <div className="flex items-center justify-between gap-3 py-3">
                    <dt className="text-ink/70">생성일</dt>
                    <dd className="text-right tabular-nums text-ink">{formatGroupDate(group.created_at)}</dd>
                </div>
                <div className="flex items-center justify-between gap-3 py-3">
                    <dt className="text-ink/70">그룹 정보 수정일</dt>
                    <dd className="text-right tabular-nums text-ink">{formatGroupDate(group.updated_at)}</dd>
                </div>
            </dl>
        </aside>
    );
}
