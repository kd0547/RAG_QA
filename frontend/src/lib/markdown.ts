/**
 * 화면 공용 마크다운 플러그인 (react-markdown의 remarkPlugins).
 *
 * remark-gfm은 기본으로 물결표 한 개(~)도 취소선으로 읽는다. 그러면 답변·문서에 흔한 범위 표기
 * "OU01~OU03, PU01~PU03"에서 두 ~ 사이가 취소선이 되고 ~는 사라진다. 그래서 한 개짜리는 끄고
 * ~~두 개로 감싼 것~~만 취소선으로 둔다.
 */
import type { Options } from 'react-markdown';
import remarkGfm from 'remark-gfm';

export const remarkPlugins: Options['remarkPlugins'] = [[remarkGfm, { singleTilde: false }]];
