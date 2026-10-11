import { describe, expect, it } from 'vitest';
import { mkdtemp, mkdir, readFile, writeFile, cp } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { WALK_ROOT, WALK_RUN, decodeFlags, loadWalk } from '../src/lib/network/walk';
import { NAV_ITEMS } from '../src/lib/site';

describe('network simulation evidence', () => {
  it('loads the manifested walk: one late probe and its on-time twin on the same path', async () => {
    const ev = await loadWalk();
    const w = ev.walk;
    expect(ev.gitSha).toMatch(/^[0-9a-f]{40}$/);
    expect(w.path[0]!.kind).toBe('gs');
    expect(w.path[w.path.length - 1]!.kind).toBe('gs');
    expect(w.fault_run.hops.map((h) => h.node_id)).toEqual(w.nofault_run.hops.map((h) => h.node_id));
    // Segments Left counts down by one per hop, from Num Hops at the ingress to 0 at the end.
    const sl = w.fault_run.hops.map((h) => h.sl);
    expect(sl[sl.length - 1]).toBe(0);
    sl.slice(1).forEach((v, i) => expect(v).toBe(Math.max(0, sl[i]! - (i === 0 ? 0 : 1))));
    // The late hop is the first with a negative margin; DEV is set there and after, never before.
    const late = w.fault_run.hops.findIndex((h) => h.node_id === w.fault_run.late_node);
    expect(late).toBeGreaterThan(0);
    expect(w.fault_run.hops[late]!.margin_ms).toBeLessThan(0);
    w.fault_run.hops.forEach((h, i) => {
      if (i > late) expect(decodeFlags(h.flags).dev).toBe(true);
      if (i < late) {
        expect(decodeFlags(h.flags).dev).toBe(false);
        if (h.margin_ms !== null) expect(h.margin_ms).toBeGreaterThanOrEqual(0);
      }
    });
    // The twin is never late and never flagged.
    expect(w.nofault_run.late_node).toBeNull();
    w.nofault_run.hops.forEach((h) => {
      expect(decodeFlags(h.flags).dev).toBe(false);
      if (h.margin_ms !== null) expect(h.margin_ms).toBeGreaterThanOrEqual(0);
    });
    // Header bytes: byte 2 is Routing Type 253, byte 3 is Segments Left as recorded.
    w.fault_run.hops.forEach((h) => {
      const b = Buffer.from(h.hex ?? '', 'hex');
      expect(b[2]).toBe(253);
      expect(b[3]).toBe(h.sl);
    });
  });

  it('refuses a walk.json that does not match its manifest', async () => {
    const tmp = await mkdtemp(path.join(os.tmpdir(), 'walk-'));
    const dir = path.join(tmp, WALK_RUN);
    await mkdir(dir, { recursive: true });
    await cp(path.join(WALK_ROOT, WALK_RUN, 'manifest.json'), path.join(dir, 'manifest.json'));
    const text = await readFile(path.join(WALK_ROOT, WALK_RUN, 'walk.json'), 'utf8');
    await writeFile(path.join(dir, 'walk.json'), text.replace('"late_node": ', '"late_node":  '));
    await expect(loadWalk(tmp, WALK_RUN)).rejects.toThrow(/does not match its manifest/);
  });

  it('is linked from the navigation', () => {
    expect(NAV_ITEMS.some((n) => n.path === 'network')).toBe(true);
  });
});
