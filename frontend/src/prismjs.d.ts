/**
 * prismjs는 타입 선언을 제공하지 않는다.
 * 전역 `Prism`을 세워주기 위해 side-effect 용도로만 import 하므로 최소 선언만 둔다.
 * (자세한 배경은 Root.tsx 의 OcrTool 주석 참고)
 */
declare module 'prismjs' {
    const Prism: unknown;
    export default Prism;
}
