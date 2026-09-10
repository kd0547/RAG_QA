/**
 * Figma 디자인(TG OCR_260721)에 쓰인 아이콘 세트.
 * 모두 currentColor를 따르므로 색은 Tailwind 유틸(text-*)로 지정한다.
 */

type IconProps = { className?: string };

/** 사이드바 상단 로고 마크 (파란 라운드 스퀘어 + 사진 글리프) */
export function LogoMark({ className = 'w-[22px] h-[22px]' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 22 22" fill="none" aria-hidden="true">
            <defs>
                <linearGradient id="tg-logo-g" x1="2" y1="2" x2="20" y2="20" gradientUnits="userSpaceOnUse">
                    <stop stopColor="#5CC0FF" />
                    <stop offset="1" stopColor="#3B82F6" />
                </linearGradient>
            </defs>
            <rect x="1.5" y="1.5" width="19" height="19" rx="5" fill="url(#tg-logo-g)" />
            <path
                d="M6 13.6l3.1-3.3a1 1 0 011.44-.02l1.7 1.72 1.5-1.6a1 1 0 011.47.02L17 12.7v2.05a1.25 1.25 0 01-1.25 1.25h-8.5A1.25 1.25 0 016 14.75v-1.15z"
                fill="#fff"
            />
            <circle cx="14.6" cy="7.6" r="1.7" fill="#fff" fillOpacity=".92" />
        </svg>
    );
}

export function UploadIcon({ className = 'w-[26px] h-[26px]' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 15.5V4.5m0 0L8.25 8.25M12 4.5l3.75 3.75" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 14.5v3.25A1.75 1.75 0 006.25 19.5h11.5a1.75 1.75 0 001.75-1.75V14.5" />
        </svg>
    );
}

export function CopyIcon({ className = 'w-3.5 h-3.5' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
            <rect x="8.5" y="8.5" width="11" height="11" rx="2.5" />
            <path strokeLinecap="round" d="M15.5 5.5A2 2 0 0013.5 3.5h-7a3 3 0 00-3 3v7a2 2 0 002 2" />
        </svg>
    );
}

export function CheckIcon({ className = 'w-3.5 h-3.5' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M5 12.5l4.5 4.5L19 7.5" />
        </svg>
    );
}

export function DownloadIcon({ className = 'w-3.5 h-3.5' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 3.5v10m0 0l-3.75-3.75M12 13.5l3.75-3.75" />
            <path strokeLinecap="round" d="M4.5 17.5v1.25a1.75 1.75 0 001.75 1.75h11.5a1.75 1.75 0 001.75-1.75V17.5" />
        </svg>
    );
}

export function DocumentIcon({ className = 'w-7 h-7' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
            <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M14 3.5H7.5A1.5 1.5 0 006 5v14a1.5 1.5 0 001.5 1.5h9A1.5 1.5 0 0018 19V7.5L14 3.5z"
            />
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.75 3.75V7.5H17.5" />
        </svg>
    );
}

export function PageIcon({ className = 'w-[7px] h-[9px]' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 14 18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path strokeLinejoin="round" d="M8.5 1H2.5A1.5 1.5 0 001 2.5v13A1.5 1.5 0 002.5 17h9a1.5 1.5 0 001.5-1.5V5.5L8.5 1z" />
        </svg>
    );
}

export function ChevronIcon({ className = 'w-2 h-2' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 8 5" fill="currentColor" aria-hidden="true">
            <path d="M.6.4h6.8c.5 0 .76.6.4.95L4.4 4.7a.55.55 0 01-.8 0L.2 1.35A.55.55 0 01.6.4z" />
        </svg>
    );
}

export function CloseIcon({ className = 'w-[9px] h-[9px]' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
            <path strokeLinecap="round" d="M1.5 1.5l9 9m0-9l-9 9" />
        </svg>
    );
}

export function RetryIcon({ className = 'w-[10px] h-[10px]' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
            <path strokeLinecap="round" d="M12.2 7a5.2 5.2 0 11-1.6-3.75" />
            <path strokeLinecap="round" strokeLinejoin="round" d="M12.4 1v3.1H9.3" />
        </svg>
    );
}

export function AlertIcon({ className = 'w-6 h-6' }: IconProps) {
    return (
        <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M11.13 3.6a1 1 0 011.74 0l8.4 14.9A1 1 0 0120.4 20H3.6a1 1 0 01-.87-1.5l8.4-14.9z" />
            <path d="M11.1 8.4h1.8l-.25 5.6h-1.3L11.1 8.4zM12 15.2a1.05 1.05 0 110 2.1 1.05 1.05 0 010-2.1z" fill="#fff" />
        </svg>
    );
}
