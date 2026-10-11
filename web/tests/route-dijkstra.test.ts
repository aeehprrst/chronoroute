/**
 * Dijkstra port (src/lib/route/dijkstra.ts): exact costs, the lowest-node-id tie-break, and
 * ground stations that never relay. Checked against a brute-force oracle on random graphs.
 */
import { describe, expect, it } from 'vitest';
import { dijkstra, pathTo, shortestPath } from '../src/lib/route/dijkstra';
import { csrFromEdges } from '../src/lib/route/topology';

function graph(n: number, edges: Array<[number, number, number]>, nonTransit: number[] = []) {
  const transit = new Uint8Array(n).fill(1);
  for (const v of nonTransit) transit[v] = 0;
  return csrFromEdges(
    n,
    edges.map((e) => e[0]),
    edges.map((e) => e[1]),
    edges.map((e) => e[2]),
    transit,
  );
}

function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Bellman-Ford with the same transit rule: the oracle for costs. */
function oracle(n: number, edges: Array<[number, number, number]>, transit: Uint8Array, s: number): number[] {
  const d = new Array<number>(n).fill(Infinity);
  d[s] = 0;
  for (let round = 0; round < n; round += 1) {
    for (const [a, b, w] of edges) {
      for (const [u, v] of [
        [a, b],
        [b, a],
      ] as const) {
        if (d[u]! === Infinity || (u !== s && !transit[u])) continue;
        if (d[u]! + w < d[v]!) d[v] = d[u]! + w;
      }
    }
  }
  return d;
}

describe('dijkstra', () => {
  it('on equal cost the LOWEST predecessor id wins, whatever the pop order', () => {
    // 0 -> 3 costs 10 via 2 (popped first, distance 4) and via 1 (distance 5): both total 10.
    const g = graph(4, [
      [0, 1, 5],
      [0, 2, 4],
      [1, 3, 5],
      [2, 3, 6],
    ]);
    const [cost, path] = shortestPath(g, 0, 3);
    expect(cost).toBe(10);
    expect(path).toEqual([0, 1, 3]);
  });

  it('never relays through a ground station (transit = 0), but may start and end at one', () => {
    // 4 and 5 are the two cities; 6 is a third city. 4-0-6-2-5 costs 4 but would relay
    // through city 6, so the answer is 4-0-1-2-5 at cost 12.
    const g = graph(
      7,
      [
        [4, 0, 1],
        [0, 6, 1],
        [6, 2, 1],
        [0, 1, 5],
        [1, 2, 5],
        [2, 5, 1],
      ],
      [4, 5, 6],
    );
    const [cost, path] = shortestPath(g, 4, 5);
    expect(path).toEqual([4, 0, 1, 2, 5]);
    expect(cost).toBe(12);
  });

  it('reports an unreachable target as [null, null]', () => {
    const g = graph(3, [[0, 1, 3]]);
    expect(shortestPath(g, 0, 2)).toEqual([null, null]);
  });

  it('matches a brute-force oracle on 300 random graphs, and every predecessor obeys the tie rule', () => {
    const r = rng(42);
    for (let trial = 0; trial < 300; trial += 1) {
      const n = 3 + Math.floor(r() * 25);
      const edges: Array<[number, number, number]> = [];
      const seen = new Set<string>();
      const m = Math.floor(r() * n * 3);
      for (let i = 0; i < m; i += 1) {
        const a = Math.floor(r() * n);
        const b = Math.floor(r() * n);
        if (a === b || seen.has(`${Math.min(a, b)}-${Math.max(a, b)}`)) continue;
        seen.add(`${Math.min(a, b)}-${Math.max(a, b)}`);
        edges.push([a, b, 1 + Math.floor(r() * 4)]); // small weights: many exact ties
      }
      const nonTransit = Array.from({ length: n }, (_, v) => v).filter(() => r() < 0.15);
      const g = graph(n, edges, nonTransit);
      const s = Math.floor(r() * n);
      const sp = dijkstra(g, s);
      const want = oracle(n, edges, g.transit, s);
      for (let v = 0; v < n; v += 1) {
        expect(sp.dist[v] ?? Infinity).toBe(want[v]);
        if (v === s || sp.dist[v] === null) continue;
        // pred[v] = min{u : u may relay (or is s), dist[u] + w(u, v) == dist[v]}
        let best = Infinity;
        for (const [a, b, w] of edges) {
          for (const [u, x] of [
            [a, b],
            [b, a],
          ] as const) {
            if (x !== v || want[u] === Infinity || (u !== s && !g.transit[u])) continue;
            if (want[u]! + w === want[v]) best = Math.min(best, u);
          }
        }
        expect(sp.pred[v]).toBe(best);
        const path = pathTo(sp, v)!;
        expect(path[0]).toBe(s);
        expect(path.slice(1, -1).every((u) => g.transit[u] === 1)).toBe(true);
      }
    }
  });

  it('csrFromEdges refuses self loops, duplicates and non-positive weights', () => {
    expect(() => graph(2, [[0, 0, 1]])).toThrow();
    expect(() => graph(2, [[0, 1, 1], [1, 0, 2]])).toThrow();
    expect(() => graph(2, [[0, 1, 0]])).toThrow();
  });
});
