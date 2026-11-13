/**
 * 백엔드가 아직 없거나 연결이 안 될 때 화면을 채우는 예시 데이터.
 * 대시보드는 API 호출이 실패하면 자동으로 이 데이터로 폴백하고 상단에 배지를 띄운다.
 */
import type { Customer, CustomerTimeline, MailDetail, MailStats, MailStatus, MailSummary } from './types';

const TODAY = new Date().toISOString().slice(0, 10);
const at = (hhmm: string) => `${TODAY}T${hhmm}:00+09:00`;
const daysAgo = (n: number, hhmm: string) => {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return `${d.toISOString().slice(0, 10)}T${hhmm}:00+09:00`;
};

export const MOCK_ROWS: MailSummary[] = [
    {
        task_id: 'TASK-1a2b3c',
        subject: 'A650 16인치 모델 RAM 최대 용량과 슬롯 구성 문의',
        sender: 'kim.jh@trigem.co.kr',
        received_at: at('14:23'),
        status: 'drafted',
    },
    {
        task_id: 'TASK-4d5e6f',
        subject: 'RTX5070 GPU 스튜디오 드라이버 버전 호환성',
        sender: 'lee.sy@partner.co.kr',
        received_at: at('13:51'),
        status: 'drafted',
    },
    {
        task_id: 'TASK-7g8h9i',
        subject: '코난LLM 온프레미스 설치 최소 요구사항',
        sender: 'park.dw@trigem.co.kr',
        received_at: at('13:40'),
        status: 'in_review',
    },
    {
        task_id: 'TASK-0j1k2l',
        subject: 'Jirisan 보드 EVT 검인 보고서 외부 공유 가능 여부',
        sender: 'm.chen@arrowtech.com',
        received_at: at('12:58'),
        status: 'drafted',
    },
    {
        task_id: 'TASK-3m4n5o',
        subject: '제품 보증 기간 연장 정책 (B2B 계약분)',
        sender: 'jung.hn@trigem.co.kr',
        received_at: at('11:30'),
        status: 'drafted',
    },
    {
        task_id: 'TASK-6p7q8r',
        subject: '[자동] 배송 지연 안내 회신',
        sender: 'noreply@trigem.co.kr',
        received_at: at('09:12'),
        status: 'failed',
    },
];

/** 검토가 끝났거나 아직 초안이 없는 메일 — 메일(전체) 페이지에서만 보인다 */
const MOCK_ARCHIVE: MailSummary[] = [
    {
        task_id: 'TASK-9s0t1u',
        subject: 'X1 Carbon 도킹 스테이션 호환 목록 요청',
        sender: 'han.ys@partner.co.kr',
        received_at: at('15:02'),
        status: 'pending',
    },
    {
        task_id: 'TASK-2v3w4x',
        subject: 'A650 BIOS 업데이트 후 팬 소음 증가 문의',
        sender: 'oh.sj@trigem.co.kr',
        received_at: at('10:47'),
        status: 'sent',
    },
    {
        task_id: 'TASK-5y6z7a',
        subject: '교육기관 대량 구매 견적 요청 (200대)',
        sender: 'admin@hanbit.ac.kr',
        received_at: at('08:55'),
        status: 'rejected',
    },
    {
        task_id: 'TASK-8b9c0d',
        subject: 'RMA 접수 절차와 소요 기간 안내 요청',
        sender: 'cs@arrowtech.com',
        received_at: daysAgo(1, '17:20'),
        status: 'sent',
    },
    {
        task_id: 'TASK-1e2f3g',
        subject: 'Windows 11 24H2 드라이버 패키지 배포 일정',
        sender: 'lim.jw@trigem.co.kr',
        received_at: daysAgo(1, '14:05'),
        status: 'sent',
    },
];

/** 전체 예시 메일 (최신순) */
export const MOCK_ALL_ROWS: MailSummary[] = [...MOCK_ROWS, ...MOCK_ARCHIVE].sort((a, b) =>
    b.received_at.localeCompare(a.received_at),
);

/** API가 없을 때 GET /mails 를 흉내 낸다 (상태 · 검색어 필터) */
export function mockList(statuses: MailStatus[], q?: string): MailSummary[] {
    const needle = q?.trim().toLowerCase();
    return MOCK_ALL_ROWS.filter(
        (r) =>
            statuses.includes(r.status) &&
            (!needle || r.subject.toLowerCase().includes(needle) || r.sender.toLowerCase().includes(needle)),
    );
}

export const MOCK_STATS: MailStats = {
    date: TODAY,
    pending_review: 5,
    sent_today: 24,
    rejected_today: 3,
    failed: 1,
    avg_review_seconds: 112,
    draft_adoption_rate: 0.79,
    sent_delta: 6,
    daily_volume: [12, 18, 9, 22, 25, 14, 7, 3, 28, 31, 19, 24, 26, 24].map((sent, i) => {
        const d = new Date();
        d.setDate(d.getDate() - (13 - i));
        return { date: d.toISOString().slice(0, 10), sent };
    }),
};

const KIM_DRAFT = `김지현 님,

문의하신 A650 16인치(Jirisan, Kraken Point / RTX5070) 모델의 메모리 사양입니다.

· 최대 확장 용량: 64GB (DDR5-5600)
· 슬롯 구성: SO-DIMM 2슬롯, 온보드 메모리 없음
· 출고 기본: 16GB (8GB×2), 듀얼 채널

64GB로 확장하려면 32GB 모듈 2개로 교체가 필요합니다. 단일 32GB(1슬롯) 구성도 부팅되지만 싱글 채널로 동작합니다.

추가 문의 있으시면 회신 부탁드립니다.
감사합니다.`;

const MOCK_DETAIL_EXTRA: Record<string, Partial<MailDetail>> = {
    'TASK-2v3w4x': {
        assignee: '나',
        body: 'A650 BIOS 1.08 업데이트 이후 유휴 상태에서도 팬이 자주 돌아 소음이 커졌다는 사용자 제보가 있습니다. 설정으로 조정 가능한지 문의드립니다.',
        draft: '오세진 님,\n\nBIOS 1.08에서 기본 팬 커브가 **성능 모드**로 변경되었습니다. BIOS 설정 > Advanced > Fan Profile 에서 `Quiet` 로 바꾸면 이전과 같은 소음 수준으로 돌아갑니다.\n\n감사합니다.',
        model: 'qwen3.8:27b',
        sources: [{ source: 'A650_BIOS_릴리스노트_1.08.pdf', page: 2, text: '기본 팬 프로파일 변경: Balanced → Performance' }],
    },
    'TASK-5y6z7a': {
        body: '교육기관 대상으로 A650 200대 구매를 검토 중입니다. 견적과 납기를 알려주세요.',
        draft: '안녕하세요,\n\n200대 기준 단가는 대당 1,290,000원이며 납기는 4주입니다.\n\n감사합니다.',
        model: 'qwen3.8:27b',
        sources: [],
    },
    'TASK-8b9c0d': {
        body: 'RMA 접수는 어디서 하고 처리까지 얼마나 걸리나요?',
        draft: '안녕하세요,\n\nRMA는 파트너 포털의 **서비스 > RMA 접수** 메뉴에서 신청하실 수 있으며, 입고 후 영업일 기준 5일 이내에 처리됩니다.\n\n감사합니다.',
        model: 'qwen3.8:27b',
        sources: [{ source: '파트너_서비스_정책_2026.pdf', page: 8, text: 'RMA 처리 기준: 입고 후 5영업일' }],
    },
    'TASK-1e2f3g': {
        body: 'Windows 11 24H2용 통합 드라이버 패키지는 언제 배포되나요?',
        draft: '임재원 님,\n\n24H2 통합 드라이버 패키지는 이번 달 셋째 주에 지원 페이지로 배포될 예정입니다.\n\n감사합니다.',
        model: 'qwen3.8:27b',
        sources: [],
    },
    'TASK-1a2b3c': {
        body: `안녕하세요. 개발본부 김지현입니다.
A650 16인치(Jirisan, Kraken Point) 모델 관련 고객사 문의가 들어왔습니다.
1) 메모리 최대 확장 용량이 얼마인지
2) 슬롯이 2개인지, 온보드 + 1슬롯 구조인지
RTX5070 탑재 모델 기준으로 확인 부탁드립니다. 감사합니다.`,
        draft: KIM_DRAFT,
        model: 'qwen3.8:27b',
        retrieval: { query_top_k: 6, rerank_top_n: 3 },
        sources: [
            { source: '사양서_일반형노트북_20.pdf', page: 4, text: '메모리 / 최대 64GB (SO-DIMM 2슬롯), 온보드 없음' },
            { source: '개발계획서_A650_16_Jirisan_Krachen_Point_RTX5070_Rev_1.0.pdf', page: 11, text: '듀얼 채널 구성, 출고 16GB (8GB x2)' },
            { source: 'TG_NPC_제품제안서_A650_16인치_Jirisan.pdf', page: 7, text: '확장성 표 - 최대 64GB DDR5-5600' },
        ],
    },
    'TASK-4d5e6f': {
        body: 'RTX5070 탑재 모델에서 NVIDIA 스튜디오 드라이버 어느 버전부터 검증됐는지, 게임 레디 드라이버와 혼용해도 되는지 문의드립니다.',
        draft: '이수영 님,\n\nRTX5070 탑재 모델은 NVIDIA Studio Driver 566.14 이상에서 검증되었습니다. Game Ready Driver도 동작하나, 콘텐츠 제작 워크로드는 Studio Driver 사용을 권장합니다.\n\n감사합니다.',
        model: 'qwen3.8:27b',
        retrieval: { query_top_k: 6, rerank_top_n: 3 },
        sources: [
            { source: 'TG_NPC_제품제안서_A650_16인치_Jirisan.pdf', page: 9, text: 'GPU 드라이버 검증 버전: Studio 566.xx' },
        ],
    },
    'TASK-7g8h9i': {
        assignee: '나',
        body: '코난LLM을 사내 서버에 온프레미스로 올리려는데 GPU/메모리/디스크 최소 사양을 알려주세요.',
        draft: '박도원 님,\n\n코난LLM 온프레미스 최소 사양은 다음과 같습니다.\n· GPU: VRAM 48GB 이상 (A6000 / L40S급)\n· 시스템 메모리: 128GB\n· 디스크: NVMe 1TB 이상\n\n감사합니다.',
        model: 'qwen3.8:27b',
        retrieval: { query_top_k: 6, rerank_top_n: 3 },
        sources: [
            { source: 'TG_AI_Powered_Station_with_코난LLM_사용자가이드_3.0.pdf', page: 22, text: '온프레미스 최소 요구사양 표' },
        ],
    },
    'TASK-0j1k2l': {
        body: 'Could you share the Jirisan board EVT qualification report and related mass-production data (A650)?',
        draft: 'Michael 님,\n\n요청하신 EVT 검인 보고서는 대외 공유 등급 확인이 필요합니다. 담당 부서 확인 후 회신드리겠습니다.\n\n감사합니다.',
        model: 'qwen3.8:27b',
        retrieval: { query_top_k: 6, rerank_top_n: 3 },
        sources: [
            { source: 'EVT_검인증_보고서_및_양산이관자료_A650.pdf', page: 1, text: '문서 접근 등급 미상' },
        ],
    },
    'TASK-3m4n5o': {
        body: 'B2B 계약분 제품의 보증 기간을 연장할 수 있는지, 연장 조건과 최대 기간을 알려주세요.',
        draft: '정하늘 님,\n\nB2B 계약분 보증 연장은 계약 부속합의서 기준으로 기본 12개월 + 최대 24개월까지 가능합니다. 연장 신청은 출고 후 6개월 이내에 접수되어야 합니다.\n\n감사합니다.',
        model: 'qwen3.8:27b',
        retrieval: { query_top_k: 6, rerank_top_n: 3 },
        sources: [
            { source: '사양서_일반형노트북_20.pdf', page: 19, text: '보증 정책 - B2B 연장 조항' },
        ],
    },
    'TASK-6p7q8r': {
        body: '배송 지연 안내에 대한 자동 회신 건. SMTP 인증 오류(535)로 전송에 2회 실패했습니다.',
        draft: '고객님, 주문하신 상품의 배송이 지연되어 안내드립니다. 예상 출고일은 영업일 기준 2일 이내입니다. 불편을 드려 죄송합니다.',
        model: 'qwen3.8:27b',
        retrieval: { query_top_k: 6, rerank_top_n: 3 },
        sources: [],
    },
};

export function mockDetail(row: MailSummary): MailDetail {
    const extra = MOCK_DETAIL_EXTRA[row.task_id] ?? {};
    // 주소의 task_id만으로 연 경우(제목·발신자 없음)는 예시 목록에서 나머지 필드를 채운다.
    const base = row.subject ? row : (MOCK_ALL_ROWS.find((r) => r.task_id === row.task_id) ?? row);
    return {
        ...base,
        assignee: extra.assignee ?? null,
        recipient: 'support-ai@trigem.co.kr',
        body: extra.body ?? '(원문 없음)',
        draft: extra.draft ?? null,
        model: extra.model ?? null,
        retrieval: extra.retrieval ?? null,
        sources: extra.sources ?? [],
        // 예시 데이터는 근거 문서마다 같은 이름의 원본이 있다고 가정한다
        attachments: [...new Set((extra.sources ?? []).map((s) => s.source))].map((name, i) => ({
            file_id: `mock-file-${i}`,
            filename: name,
            mime_type: 'application/pdf',
            size_bytes: 1_200_000 + i * 850_000,
            available: true,
        })),
        created_at: base.received_at,
        updated_at: base.received_at,
    };
}

// ---------- 고객방 예시 (GET /customers 실패 시) ----------

export const MOCK_CUSTOMERS: Customer[] = [
    {
        sender: 'kim.jh@trigem.co.kr',
        mail_count: 3,
        first_received_at: daysAgo(6, '09:12'),
        last_received_at: at('14:23'),
        last_subject: 'A650 16인치 모델 RAM 최대 용량과 슬롯 구성 문의',
        last_task_id: 'TASK-1a2b3c',
        status_counts: { drafted: 1, sent: 2 },
        needs_review: 1,
    },
    {
        sender: 'park.sy@partner.co.kr',
        mail_count: 1,
        first_received_at: daysAgo(2, '10:40'),
        last_received_at: daysAgo(2, '10:40'),
        last_subject: 'N5800 KC 인증서 사본 요청',
        last_task_id: 'TASK-mock-kc',
        status_counts: { failed: 1 },
        needs_review: 1,
    },
];

const MOCK_TIMELINES: Record<string, CustomerTimeline> = {
    'kim.jh@trigem.co.kr': {
        sender: 'kim.jh@trigem.co.kr',
        total: 3,
        next_before: null,
        items: [
            {
                task_id: 'TASK-mock-old', subject: 'N5800 무게 문의', status: 'sent', received_at: daysAgo(6, '09:12'),
                events: [
                    { type: 'received', at: daysAgo(6, '09:12'), body: 'N5800 무게가 얼마인가요?', truncated: false, attachments: [] },
                    {
                        type: 'draft', at: null, run_id: null, label: null, answer: 'N5800의 무게는 약 1.65kg입니다.',
                        truncated: false, text_source: 'task', current: true, inferred: true, skills: [],
                    },
                    {
                        type: 'send', at: daysAgo(6, '11:02'), outcome: 'sent', recipient: null, body: null, truncated: false,
                        attachments: [], detail: null, inferred: true,
                    },
                ],
            },
            {
                task_id: 'TASK-mock-kc2', subject: 'N5800 KC 인증번호', status: 'sent', received_at: daysAgo(3, '15:30'),
                events: [
                    {
                        type: 'received', at: daysAgo(3, '15:30'), body: 'N5800 KC 인증번호 알려주세요.', truncated: false,
                        attachments: [{ filename: '요청서.pdf', type: 'pdf' }],
                    },
                    {
                        type: 'draft', at: daysAgo(3, '15:31'), run_id: 'rmock1', label: '메일(첨부 1건, 반려 없음)',
                        answer: '| 인증 | 번호 |\n|---|---|\n| KC 안전 | HU07xxxx-xxxx |', truncated: false, text_source: 'run',
                        current: false, inferred: false, skills: [{ name: 'mail-reply-style', digest: 'mock0001' }],
                    },
                    { type: 'reject', at: daysAgo(3, '16:05'), review_id: 1, reason: '표 말고 문장으로 써 주세요.', truncated: false, requeue: true },
                    {
                        type: 'draft', at: daysAgo(3, '16:06'), run_id: 'rmock2', label: '메일 반려 반영(review_id=1, 같은 대화)',
                        answer: 'N5800의 KC 안전 인증번호는 HU07xxxx-xxxx입니다.', truncated: false, text_source: 'run',
                        current: true, inferred: false,
                        skills: [{ name: 'mail-reply-style', digest: 'mock0001' }, { name: 'revise-after-reject', digest: 'mock0002' }],
                    },
                    {
                        type: 'send', at: daysAgo(3, '16:20'), outcome: 'sent', recipient: 'kim.jh@trigem.co.kr',
                        body: 'N5800의 KC 안전 인증번호는 HU07xxxx-xxxx입니다.', truncated: false, attachments: ['KC인증서.pdf'],
                        detail: '250 OK', inferred: false,
                    },
                ],
            },
            {
                task_id: 'TASK-1a2b3c', subject: 'A650 16인치 모델 RAM 최대 용량과 슬롯 구성 문의', status: 'drafted',
                received_at: at('14:23'),
                events: [
                    { type: 'received', at: at('14:23'), body: 'A650 16인치 RAM 최대 용량과 슬롯 구성이 궁금합니다.', truncated: false, attachments: [] },
                    {
                        type: 'draft', at: at('14:24'), run_id: 'rmock3', label: '메일(첨부 0건, 반려 없음)',
                        answer: 'A650 16인치는 SO-DIMM 슬롯 2개, 최대 64GB까지 지원합니다.', truncated: false, text_source: 'run',
                        current: true, inferred: false, skills: [{ name: 'mail-reply-style', digest: 'mock0001' }],
                    },
                ],
            },
        ],
    },
    'park.sy@partner.co.kr': {
        sender: 'park.sy@partner.co.kr',
        total: 1,
        next_before: null,
        items: [
            {
                task_id: 'TASK-mock-kc', subject: 'N5800 KC 인증서 사본 요청', status: 'failed', received_at: daysAgo(2, '10:40'),
                events: [
                    { type: 'received', at: daysAgo(2, '10:40'), body: 'KC 인증서 사본을 받을 수 있을까요?', truncated: false, attachments: [] },
                    {
                        type: 'run_failed', at: daysAgo(2, '10:42'), run_id: 'rmock4', label: '메일(첨부 0건, 반려 없음)',
                        status: 'limit', error: '모델 호출 한도(20회)를 넘어 답변을 만들지 못했습니다',
                    },
                ],
            },
        ],
    },
};

export function mockCustomers(q?: string): Customer[] {
    const needle = (q ?? '').trim().toLowerCase();
    return needle
        ? MOCK_CUSTOMERS.filter((c) => c.sender.includes(needle) || c.last_subject.toLowerCase().includes(needle))
        : MOCK_CUSTOMERS;
}

export function mockTimeline(sender: string): CustomerTimeline {
    return MOCK_TIMELINES[sender] ?? { sender, total: 0, next_before: null, items: [] };
}
