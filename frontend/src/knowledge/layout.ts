/**
 * 그래프 배치 (Fruchterman-Reingold 힘 기반 배치). 라이브러리 없이 계산만 한다.
 *
 * - 이미 자리가 있는 노드는 그 자리에서 시작해, 다시 불러와도 그림이 크게 흔들리지 않는다.
 * - 새 노드는 이미 놓인 이웃 근처, 없으면 원 둘레에 놓고 시작한다 (같은 데이터면 같은 그림).
 * - 고정(pinned)한 노드는 움직이지 않는다 (사용자가 끌어다 놓은 노드).
 */
export interface Point {
    x: number;
    y: number;
}

interface LayoutEdge {
    source: number;
    target: number;
}

const IDEAL = 110; // 이웃 사이 기본 거리
const ITERATIONS = 320;
// 이보다 먼 노드끼리는 밀어내지 않는다. 안 그러면 연결 없는 노드가 화면 밖 멀리 밀려난다
const REPULSION_RANGE2 = (IDEAL * 4) ** 2;
const GRAVITY = 0.06;

export function layoutGraph(
    nodeIds: number[],
    edges: LayoutEdge[],
    previous: Map<number, Point>,
    pinned: Set<number> = new Set(),
): Map<number, Point> {
    const n = nodeIds.length;
    const result = new Map<number, Point>();
    if (n === 0) return result;

    const index = new Map(nodeIds.map((id, i) => [id, i]));
    const links = edges
        .map((e) => [index.get(e.source), index.get(e.target)] as const)
        .filter((pair): pair is readonly [number, number] => pair[0] !== undefined && pair[1] !== undefined && pair[0] !== pair[1]);
    const neighbors: number[][] = nodeIds.map(() => []);
    for (const [a, b] of links) {
        neighbors[a].push(b);
        neighbors[b].push(a);
    }

    // 시작 위치
    const xs = new Float64Array(n);
    const ys = new Float64Array(n);
    const placed = new Uint8Array(n);
    nodeIds.forEach((id, i) => {
        const p = previous.get(id);
        if (p) {
            xs[i] = p.x;
            ys[i] = p.y;
            placed[i] = 1;
        }
    });
    const radius = IDEAL * Math.max(1, Math.sqrt(n) / 2);
    nodeIds.forEach((_, i) => {
        if (placed[i]) return;
        const anchor = neighbors[i].find((j) => placed[j]);
        const angle = (i * 2.399963) % (Math.PI * 2); // 황금각: 겹치지 않게 흩어 놓는다
        if (anchor !== undefined) {
            xs[i] = xs[anchor] + Math.cos(angle) * IDEAL * 0.6;
            ys[i] = ys[anchor] + Math.sin(angle) * IDEAL * 0.6;
        } else {
            const r = radius * Math.sqrt((i + 0.5) / n);
            xs[i] = Math.cos(angle) * r;
            ys[i] = Math.sin(angle) * r;
        }
        placed[i] = 1;
    });

    const fixed = nodeIds.map((id) => pinned.has(id));
    const k = IDEAL;
    const dx = new Float64Array(n);
    const dy = new Float64Array(n);
    // 이미 배치된 그래프를 조금만 고칠 때는 덜 흔든다
    const reused = nodeIds.filter((id) => previous.has(id)).length / n;
    let temperature = IDEAL * (reused > 0.8 ? 0.35 : 1.2);
    const cooling = temperature / (ITERATIONS + 1);

    for (let iter = 0; iter < ITERATIONS; iter++) {
        dx.fill(0);
        dy.fill(0);
        for (let i = 0; i < n; i++) {
            for (let j = i + 1; j < n; j++) {
                let ddx = xs[i] - xs[j];
                let ddy = ys[i] - ys[j];
                let dist2 = ddx * ddx + ddy * ddy;
                if (dist2 > REPULSION_RANGE2) continue;
                if (dist2 < 0.01) {
                    ddx = (i - j) * 0.1;
                    ddy = 0.1;
                    dist2 = ddx * ddx + ddy * ddy;
                }
                const force = (k * k) / dist2; // (k²/d) / d — 방향 벡터 정규화 포함
                dx[i] += ddx * force;
                dy[i] += ddy * force;
                dx[j] -= ddx * force;
                dy[j] -= ddy * force;
            }
        }
        for (const [a, b] of links) {
            const ddx = xs[a] - xs[b];
            const ddy = ys[a] - ys[b];
            const dist = Math.sqrt(ddx * ddx + ddy * ddy) || 0.01;
            const force = dist / k; // (d²/k) / d
            dx[a] -= ddx * force;
            dy[a] -= ddy * force;
            dx[b] += ddx * force;
            dy[b] += ddy * force;
        }
        for (let i = 0; i < n; i++) {
            if (fixed[i]) continue;
            // 흩어진 덩어리가 멀리 떠나지 않게 가운데로 약하게 당긴다
            dx[i] -= xs[i] * GRAVITY;
            dy[i] -= ys[i] * GRAVITY;
            const len = Math.sqrt(dx[i] * dx[i] + dy[i] * dy[i]) || 1;
            const step = Math.min(len, temperature);
            xs[i] += (dx[i] / len) * step;
            ys[i] += (dy[i] / len) * step;
        }
        temperature = Math.max(temperature - cooling, 0.5);
    }

    nodeIds.forEach((id, i) => result.set(id, { x: xs[i], y: ys[i] }));
    return result;
}

/** 노드들을 감싸는 상자 (여백 포함) */
export function bounds(points: Iterable<Point>, padding = 60): { minX: number; minY: number; width: number; height: number } {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const p of points) {
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x);
        maxY = Math.max(maxY, p.y);
    }
    if (!Number.isFinite(minX)) return { minX: -200, minY: -150, width: 400, height: 300 };
    return {
        minX: minX - padding,
        minY: minY - padding,
        width: Math.max(maxX - minX + padding * 2, 200),
        height: Math.max(maxY - minY + padding * 2, 160),
    };
}
