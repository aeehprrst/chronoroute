/**
 * The two shell scripts the deploy workflow relies on to choose its data:
 *   scripts/newest-snapshot.sh      which snapshot folders count, and their order;
 *   scripts/build-tested-data.sh    newest snapshot that passes, else fall back to older ones.
 * The real data build and test steps are replaced by tiny stub executables (the script's
 * CR_BUILD_DATA / CR_TEST hooks), so this runs in well under a second and never touches
 * public/data. Fixtures live in a fresh temporary folder that is removed afterwards.
 */
import { afterAll, describe, expect, it } from 'vitest';
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const SCRIPTS = path.resolve(import.meta.dirname, '..', 'scripts');
// The project keeps scratch files under /tmp/cr-sb when it exists (development machine).
const TMP_BASE = existsSync('/tmp/cr-sb') ? '/tmp/cr-sb' : os.tmpdir();
const tmp = mkdtempSync(path.join(TMP_BASE, 'ci-scripts-'));
afterAll(() => rmSync(tmp, { recursive: true, force: true }));

/** A snapshot folder; `supgp` = it holds a SupGP download; `marks` = stub instructions. */
function snapshot(root: string, name: string, supgp = true, marks: string[] = []): string {
  const dir = path.join(root, name);
  mkdirSync(dir, { recursive: true });
  if (supgp) {
    writeFileSync(path.join(dir, 'starlink_supgp.json'), '[]');
    writeFileSync(path.join(dir, 'supgp_headers.txt'), 'HTTP/1.1 200 OK\n\n');
  } else {
    writeFileSync(path.join(dir, 'starlink_gp.json'), '[]');
  }
  for (const m of marks) writeFileSync(path.join(dir, m), '');
  return dir;
}

function run(script: string, args: string[], env: Record<string, string> = {}) {
  const githubOutput = path.join(tmp, `out-${Math.random().toString(36).slice(2)}`);
  const summary = `${githubOutput}.summary`;
  // Always point GITHUB_OUTPUT / GITHUB_STEP_SUMMARY at scratch files: inside a real GitHub
  // job they are set, and this test must never write into the job's own outputs.
  const res = spawnSync('bash', [path.join(SCRIPTS, script), ...args], {
    encoding: 'utf8',
    env: { ...process.env, GITHUB_OUTPUT: githubOutput, GITHUB_STEP_SUMMARY: summary, ...env },
  });
  const read = (f: string) => (existsSync(f) ? readFileSync(f, 'utf8') : '');
  return { status: res.status, stdout: res.stdout, stderr: res.stderr, output: read(githubOutput), summary: read(summary) };
}

// Two roots, as in CI: committed data/pinned and the downloads kept in the Actions cache.
const committed = path.join(tmp, 'committed');
const cache = path.join(tmp, 'cache');
const s1358 = snapshot(committed, '20261010T1358Z-celestrak');
const s2035 = snapshot(cache, '20261010T2035Z-celestrak', true, ['FAIL_BUILD']);
const s0200 = snapshot(committed, '20261011T0200Z-celestrak', true, ['FAIL_TEST']);
snapshot(cache, '20261011T0600Z-celestrak', false); // GP only: never a candidate
mkdirSync(path.join(cache, '20261011T1000Z-celestrak.rejected')); // rejected download
mkdirSync(path.join(cache, '.20261011T1200Z-celestrak.x1y2')); // fetch.py staging folder

// Stub steps: fail when the snapshot carries the corresponding mark; log every call.
const calls = path.join(tmp, 'calls.log');
const stub = (name: string, mark: string) => {
  const file = path.join(tmp, name);
  writeFileSync(file, `#!/usr/bin/env bash\necho "${name} $1" >> "${calls}"\n[ ! -e "$1/${mark}" ]\n`, { mode: 0o755 });
  return file;
};
const hooks = { CR_BUILD_DATA: stub('build', 'FAIL_BUILD'), CR_TEST: stub('test', 'FAIL_TEST') };

describe('newest-snapshot.sh', () => {
  it('prints the newest folder with a SupGP download across all roots', () => {
    const r = run('newest-snapshot.sh', [committed, cache]);
    expect(r.status).toBe(0);
    expect(r.stdout).toBe(`${s0200}\n`);
  });

  it('--all lists every such folder newest first, skipping GP-only, rejected and staging folders', () => {
    const r = run('newest-snapshot.sh', ['--all', committed, cache]);
    expect(r.status).toBe(0);
    expect(r.stdout.trim().split('\n')).toEqual([s0200, s2035, s1358]);
  });

  it('fails with exit code 2 when there is no candidate', () => {
    const empty = path.join(tmp, 'empty');
    mkdirSync(empty);
    const r = run('newest-snapshot.sh', [empty]);
    expect(r.status).toBe(2);
    expect(r.stderr).toMatch(/no <YYYYMMDDTHHMMZ>-celestrak folder/);
  });
});

describe('build-tested-data.sh', () => {
  it('with MAX_SNAPSHOTS=1 tries only the newest (committed: 0200Z fails its tests -> exit 1)', () => {
    writeFileSync(calls, '');
    const r = run('build-tested-data.sh', [committed], { ...hooks, MAX_SNAPSHOTS: '1' });
    expect(r.status).toBe(1);
    expect(readFileSync(calls, 'utf8').trim().split('\n')).toEqual([`build ${s0200}`, `test ${s0200}`]);
  });

  it('falls back past a snapshot that fails the build and one that fails the tests', () => {
    writeFileSync(calls, '');
    const r = run('build-tested-data.sh', [committed, cache], hooks);
    expect(r.status, r.stdout + r.stderr).toBe(0);
    expect(r.output).toContain(`snapshot=${s1358}\n`);
    expect(r.output).toContain('fallback=true\n');
    expect(r.stdout).toContain('::warning title=Older orbit snapshot deployed::20261010T1358Z-celestrak');
    expect(r.summary).toContain('Older orbit snapshot deployed');
    // newest first; a failed build skips that snapshot's tests
    expect(readFileSync(calls, 'utf8').trim().split('\n')).toEqual([
      `build ${s0200}`,
      `test ${s0200}`,
      `build ${s2035}`,
      `build ${s1358}`,
      `test ${s1358}`,
    ]);
  });

  it('stops after MAX_SNAPSHOTS candidates and deploys nothing when none passed', () => {
    const r = run('build-tested-data.sh', [committed, cache], { ...hooks, MAX_SNAPSHOTS: '2' });
    expect(r.status).toBe(1);
    expect(r.output).toBe('');
    expect(r.stdout).toContain('::error title=No deployable snapshot::');
    expect(r.summary).toContain('Nothing deployed');
  });

  it('reports fallback=false when the newest passes', () => {
    const only = path.join(tmp, 'only');
    const good = snapshot(only, '20261012T0000Z-celestrak');
    snapshot(only, '20261011T0000Z-celestrak');
    const r = run('build-tested-data.sh', [only], hooks);
    expect(r.status).toBe(0);
    expect(r.output).toBe(`snapshot=${good}\nfallback=false\n`);
    expect(r.stdout).not.toContain('::warning');
  });

  it('rejects a MAX_SNAPSHOTS that is not a positive integer', () => {
    expect(run('build-tested-data.sh', [committed], { ...hooks, MAX_SNAPSHOTS: '0' }).status).toBe(2);
    expect(run('build-tested-data.sh', [committed], { ...hooks, MAX_SNAPSHOTS: 'x' }).status).toBe(2);
  });
});
