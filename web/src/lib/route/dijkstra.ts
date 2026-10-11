/**
 * Shortest paths with integer nanosecond weights: a port of sim/chronoroute/route/dijkstra.py.
 *
 * Binary heap of (distance, node) pairs, ordered by distance and then by node id, exactly
 * like Python's heapq on tuples. The tie-break every implementation must reproduce:
 *
 *     pred[v] = the LOWEST node id u with dist[u] + w(u, v) == dist[v]
 *
 * It depends only on the exact distances, not on the order the heap pops nodes. Weights are
 * integers far below 2^53, so every sum here is exact in a JavaScript number.
 *
 * Transit: a node with transit = 0 (a ground station) can be reached and can be the source,
 * but is never expanded otherwise, so a path never relays through a third city. The search
 * stops as soon as the target is settled, as in Python.
 */
import type { CsrGraph } from './topology';

/** Min-heap of [distance, node], ordered by distance, then node id. */
class PairHeap {
  private readonly d: number[] = [];
  private readonly n: number[] = [];

  get size(): number {
    return this.d.length;
  }

  private less(i: number, j: number): boolean {
    const di = this.d[i]!;
    const dj = this.d[j]!;
    return di < dj || (di === dj && this.n[i]! < this.n[j]!);
  }

  private swap(i: number, j: number): void {
    [this.d[i], this.d[j]] = [this.d[j]!, this.d[i]!];
    [this.n[i], this.n[j]] = [this.n[j]!, this.n[i]!];
  }

  push(dist: number, node: number): void {
    this.d.push(dist);
    this.n.push(node);
    let i = this.d.length - 1;
    while (i > 0) {
      const parent = (i - 1) >> 1;
      if (!this.less(i, parent)) break;
      this.swap(i, parent);
      i = parent;
    }
  }

  pop(): [number, number] {
    const top: [number, number] = [this.d[0]!, this.n[0]!];
    const lastD = this.d.pop()!;
    const lastN = this.n.pop()!;
    if (this.d.length > 0) {
      this.d[0] = lastD;
      this.n[0] = lastN;
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        const r = l + 1;
        let m = i;
        if (l < this.d.length && this.less(l, m)) m = l;
        if (r < this.d.length && this.less(r, m)) m = r;
        if (m === i) break;
        this.swap(i, m);
        i = m;
      }
    }
    return top;
  }
}

export interface ShortestPaths {
  source: number;
  /** dist[v] in ns, or null if not reached (or not finished, when the search stopped early). */
  dist: Array<number | null>;
  /** pred[v], or -1 (source / unreachable). */
  pred: Int32Array;
}

/** Dijkstra from `source`, stopping once `target` (if given) is settled. */
export function dijkstra(g: CsrGraph, source: number, target: number | null = null): ShortestPaths {
  const n = g.nNodes;
  if (!(Number.isInteger(source) && source >= 0 && source < n)) throw new RangeError(`source ${source} is not a node`);
  const dist = new Float64Array(n).fill(Infinity);
  const pred = new Int32Array(n).fill(-1);
  const done = new Uint8Array(n);
  dist[source] = 0;
  const heap = new PairHeap();
  heap.push(0, source);
  while (heap.size > 0) {
    const [d, u] = heap.pop();
    if (done[u]) continue; // a stale entry (u was improved later)
    done[u] = 1;
    if (u === target) break;
    if (u !== source && !g.transit[u]) continue; // reachable, but may not relay
    for (let i = g.indptr[u]!; i < g.indptr[u + 1]!; i += 1) {
      const v = g.indices[i]!;
      const nd = d + g.weights[i]!;
      if (nd < dist[v]!) {
        dist[v] = nd;
        pred[v] = u;
        heap.push(nd, v);
      } else if (nd === dist[v] && u < pred[v]!) {
        pred[v] = u; // equal cost: the lower predecessor id wins
      }
    }
  }
  return { source, dist: Array.from(dist, (x) => (x === Infinity ? null : x)), pred };
}

/** Node list source .. target of the canonical path, or null when the target is unreachable. */
export function pathTo(sp: ShortestPaths, target: number): number[] | null {
  if (sp.dist[target] === null) return null;
  const path = [target];
  while (path[path.length - 1] !== sp.source) {
    const prev = sp.pred[path[path.length - 1]!]!;
    if (prev < 0) throw new Error('broken predecessor chain');
    path.push(prev);
  }
  return path.reverse();
}

/** [cost_ns, nodes] of the canonical shortest path, or [null, null]. */
export function shortestPath(g: CsrGraph, source: number, target: number): [number, number[]] | [null, null] {
  const sp = dijkstra(g, source, target);
  const d = sp.dist[target];
  if (d === null || d === undefined) return [null, null];
  return [d, pathTo(sp, target)!];
}
