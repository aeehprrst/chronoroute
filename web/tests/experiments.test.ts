import { afterEach, describe, expect, it } from 'vitest';
import { createHash } from 'node:crypto';
import {
  mkdtemp,
  mkdir,
  readFile,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { serializeProps } from 'astro/runtime/server/serialize.js';
import {
  E0_CHECK_KINDS,
  EXPERIMENTS,
  type ExperimentDefinition,
} from '../src/lib/experiments/catalog';
import {
  loadExperiment,
  manifestSummary,
  RESULTS_ROOT,
} from '../src/lib/experiments/load';
import {
  parseCsv,
  numeric,
  formatValue,
  formatPValue,
  formatCell,
  isPValueColumn,
  selectRows,
  chartModel,
  lossCases,
  verdict,
  explorerProps,
  verifySummaryBytes,
  ranges,
  type Row,
} from '../src/lib/experiments/data';
import ResultsExplorer from '../src/components/experiments/ResultsExplorer';

const scratch: string[] = [];
afterEach(async () => {
  await Promise.all(
    scratch.splice(0).map((p) => rm(p, { recursive: true, force: true })),
  );
});
const byId = (id: string) => EXPERIMENTS.find((e) => e.id === id)!;
const e16 = () => byId('E16');
const props = async (def: ExperimentDefinition) => {
  const data = await loadExperiment(def);
  return explorerProps(
    def,
    data.rows,
    data.columns,
    data.evidence,
    `/chronoroute/experiments/${def.slug}/summary.csv`,
  );
};
const arrayBuffer = (b: Buffer): ArrayBuffer =>
  b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength) as ArrayBuffer;

async function fixture(def = e16(), extra: string[] = []) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'experiment-site-'));
  scratch.push(root);
  const dir = path.join(root, def.id, def.run);
  await mkdir(dir, { recursive: true });
  for (const name of ['summary.csv', 'manifest.json', ...extra])
    await writeFile(
      path.join(dir, name),
      await readFile(path.join(RESULTS_ROOT, def.id, def.run, name)),
    );
  return { root, dir };
}

describe('experiment evidence contract', () => {
  it('parses scientific CSV including CRLF, quoted commas, escaped quotes and multiline fields', () => {
    expect(parseCsv('name,value\r\n"a,b",inf\r\n"a""b\nc",\r\n')).toEqual({
      columns: ['name', 'value'],
      rows: [
        { name: 'a,b', value: 'inf' },
        { name: 'a"b\nc', value: '' },
      ],
    });
    for (const text of [
      'a,a\n1,2\n',
      'a,b\n1\n',
      'a\n"unclosed',
      'a\n"ok"bad',
      'a\nNaN\n',
      '',
    ])
      expect(() => parseCsv(text)).toThrow();
  });
  it('retains infinite and undefined results without turning them into zero or finite values', () => {
    expect(numeric('inf')).toBe(Infinity);
    expect(numeric('-inf')).toBe(-Infinity);
    expect(numeric('')).toBeNull();
    expect(numeric('0')).toBe(0);
    for (const value of ['NaN', '1garbage'])
      expect(() => numeric(value)).toThrow();
    expect(formatValue('inf')).toBe('∞');
    expect(formatValue('')).toBe('undefined');
    expect(formatValue('0')).toBe('0');
  });
  it('loads only the reviewed summaries and their manifests, preserving original download bytes', async () => {
    expect(EXPERIMENTS.map((e) => e.slug)).toEqual([
      'e0',
      'e1',
      'e2',
      'e4',
      'e5',
      'e16',
    ]);
    for (const def of EXPERIMENTS) {
      const data = await loadExperiment(def);
      const source = await readFile(
        path.join(RESULTS_ROOT, def.id, def.run, 'summary.csv'),
      );
      expect(Buffer.from(data.csvText).equals(source)).toBe(true);
      expect(data.manifest.dirty).toBe(false);
      expect(data.rows.length).toBeGreaterThan(0);
      expect(
        verdict(def, data.rows, data.contrasts?.rows ?? null).summary,
      ).not.toBe('');
      expect(!!data.contrasts).toBe(!!def.contrasts);
    }
  });
  it('uses the superseding E0 and E2 releases', async () => {
    expect(byId('E00').run).toBe('20261011T214507Z');
    expect(byId('E02').run).toBe('20261011T214624Z-confirmatory');
    const e0 = await loadExperiment(byId('E00'));
    const checks = new Set(e0.rows.map((r) => r['check']));
    for (const name of ['gsl_visibility_complete', 'wire_golden_fixed'])
      expect(checks.has(name)).toBe(true);
    // Every gate row is classified as an external reference, self-consistency or invariant.
    for (const check of checks) expect(E0_CHECK_KINDS[check!]).toBeDefined();
    const e2 = await loadExperiment(byId('E02'));
    expect(e2.manifest.outputs.map((o) => o.path)).toContain(
      'capture_frames.csv.gz',
    );
    expect(byId('E02').limitations.join(' ')).toContain('capture_frames.csv.gz');
  });
  it('refuses a changed paired-contrast file even when the summary is intact', async () => {
    const def = byId('E05');
    const { root, dir } = await fixture(def, ['paired_contrasts.csv']);
    await expect(loadExperiment(def, root)).resolves.toBeTruthy();
    const file = path.join(dir, 'paired_contrasts.csv');
    await writeFile(file, (await readFile(file, 'utf8')).replace('C5', 'C2'));
    await expect(loadExperiment(def, root)).rejects.toThrow(
      /paired_contrasts\.csv hash or size/,
    );
    await rm(file);
    await expect(loadExperiment(def, root)).rejects.toThrow(/paired_contrasts/);
  });
  it('refuses a missing manifest, changed summary, unlisted summary, dirty source or invalid preregistration', async () => {
    const { root, dir } = await fixture();
    const file = path.join(dir, 'manifest.json');
    const original = await readFile(file, 'utf8');
    await rm(file);
    await expect(loadExperiment(e16(), root)).rejects.toThrow(/manifest/);
    for (const change of [
      (m: any) => {
        m.outputs = [];
      },
      (m: any) => {
        m.dirty = true;
      },
      (m: any) => {
        m.config.prereg_git_sha = 'unknown';
      },
    ]) {
      const m = JSON.parse(original);
      change(m);
      await writeFile(file, JSON.stringify(m));
      await expect(loadExperiment(e16(), root)).rejects.toThrow();
    }
    await writeFile(file, original);
    await writeFile(
      path.join(dir, 'summary.csv'),
      'endpoint,estimate\npdr,0\n',
    );
    await expect(loadExperiment(e16(), root)).rejects.toThrow(/hash|size/);
  });
  it('refuses NaNs even when the summary hash has been updated', async () => {
    const { root, dir } = await fixture();
    const csv = (await readFile(path.join(dir, 'summary.csv'), 'utf8')).replace(
      '0.0',
      'NaN',
    );
    await writeFile(path.join(dir, 'summary.csv'), csv);
    const m = JSON.parse(
      await readFile(path.join(dir, 'manifest.json'), 'utf8'),
    );
    const entry = m.outputs.find((r: any) => r.path === 'summary.csv');
    entry.sha256 = createHash('sha256').update(csv).digest('hex');
    entry.size_bytes = Buffer.byteLength(csv);
    await writeFile(path.join(dir, 'manifest.json'), JSON.stringify(m));
    await expect(loadExperiment(e16(), root)).rejects.toThrow(/NaN/);
  });
});

describe('results presentation', () => {
  it('keeps the selected E1 rule and primary event setting alongside every comparator', async () => {
    const def = EXPERIMENTS.find((e) => e.id === 'E01')!;
    const data = await loadExperiment(def);
    const rows = selectRows(def, data.rows, {
      const: 'C5',
      condition: 'rate-0.3-middle',
      selected: true,
      k: '2',
    });
    expect(rows).toHaveLength(7);
    expect(rows.some((r) => r.scheme === 'lq')).toBe(true);
    expect(
      rows
        .filter((r) => r.scheme === 'chronoroute')
        .every((r) => r.selected === 'True'),
    ).toBe(true);
    expect(
      selectRows(def, data.rows, {
        const: 'C5',
        condition: 'rate-0.3-middle',
        selected: false,
        k: '2',
      }).length,
    ).toBeGreaterThan(rows.length);
  });
  it('renders confidence intervals including degenerate ones and keeps unplottable tails explicit', () => {
    const metric = {
      key: 'mean',
      lo: 'lo',
      hi: 'hi',
      label: 'Latency',
      unit: 's',
    };
    const model = chartModel(
      [
        { scheme: 'a', mean: '1', lo: '0.8', hi: '1.2' },
        { scheme: 'b', mean: '1', lo: '1', hi: '1' },
        { scheme: 'c', mean: 'inf', lo: 'inf', hi: 'inf' },
        { scheme: 'd', mean: '', lo: '', hi: '' },
      ],
      metric,
    );
    expect(model.points).toHaveLength(2);
    expect(model.omitted).toHaveLength(2);
    expect(
      model.points.every((p) =>
        [p.x, p.y, p.lowY, p.highY].every(Number.isFinite),
      ),
    ).toBe(true);
    expect(() => chartModel([{ mean: '1', lo: '2', hi: '0' }], metric)).toThrow(
      /interval/,
    );
  });
  it('reports actual disadvantages and unsupported visited-policy advantages', async () => {
    const e2 = EXPERIMENTS.find((e) => e.id === 'E02')!;
    const two = await loadExperiment(e2);
    expect(lossCases(e2, two.rows).some((r) => r.competitor === 'crh16')).toBe(
      true,
    );
    const e5 = EXPERIMENTS.find((e) => e.id === 'E05')!;
    const five = await loadExperiment(e5);
    expect(
      lossCases(e5, five.rows).some((r) => r.competitor === 'continue'),
    ).toBe(true);
    expect(
      lossCases(e5, five.rows).some(
        (r) => r.policy === 'grid_detour' && r.competitor === 'greedy_visited',
      ),
    ).toBe(true);
    const tied = [
      {
        const: 'C2',
        condition: 'trigger',
        scheme: 'greedy_visited',
        stuck_rate_mean: '0',
      },
      {
        const: 'C2',
        condition: 'trigger',
        scheme: 'greedy_pure',
        stuck_rate_mean: '0',
      },
    ];
    expect(
      lossCases(e5, tied).some((r) => r.note.includes('unsupported')),
    ).toBe(true);
    expect(verdict(e5, five.rows, five.contrasts!.rows).summary).toMatch(
      /^Mixed/,
    );
    expect(
      verdict(e16(), [{ complete: 'True', equivalent: 'False' }]).summary,
    ).toMatch(/unestablished/);
  });
  it('server-renders usable charts and a data table without JavaScript, with safe escaped content', async () => {
    for (const def of EXPERIMENTS) {
      const island = await props(def);
      const html = renderToStaticMarkup(createElement(ResultsExplorer, island));
      expect(html).toContain('<svg');
      expect(html).toContain('<circle');
      expect(html).toContain('<table');
      expect(html).toMatch(/<tbody><tr>/);
      expect(html).not.toContain('NaN');
      // Every SVG tooltip carries text (an array child renders an empty <title> in React 19).
      expect(html).toContain('<title>');
      expect(html).not.toContain('<title></title>');
    }
    const e1 = await props(byId('E01'));
    const e1html = renderToStaticMarkup(createElement(ResultsExplorer, e1));
    // The first page of the initial selection is server-rendered; other selections wait for
    // the hash-checked download.
    expect(e1html).toContain('rate-0.3-middle');
    expect(e1html).toContain(`out of ${e1.totalRows}`);
    expect(e1html).toMatch(/<select[^>]*disabled/);
    const island = await props(e16());
    const injected = renderToStaticMarkup(
      createElement(ResultsExplorer, {
        ...island,
        rows: [{ ...island.rows[0]!, condition: '<script>bad()</script>' }],
      }),
    );
    expect(injected).not.toContain('<script>bad()');
    expect(injected).toContain('&lt;script&gt;');
  });
  it('keeps the island small: only the initial selection is serialised, never the manifest', async () => {
    for (const def of EXPERIMENTS) {
      const island = await props(def);
      // What Astro writes into the page for the island's props, HTML-escaped as an attribute.
      const attribute = serializeProps(island).replace(/"/g, '&quot;');
      expect(attribute.length).toBeLessThan(200_000);
      expect(JSON.stringify(island)).not.toContain('"outputs"');
    }
    const e1 = await props(byId('E01'));
    expect(e1.totalRows).toBe(1620);
    expect(e1.rows.length).toBe(7);
    expect(e1.options.condition).toContain('delay-4000000-middle');
    const page = await readFile(
      path.resolve('src/pages/experiments/[experiment]/index.astro'),
      'utf8',
    );
    expect(page).not.toContain('manifestText');
    expect(page).toContain('explorerProps(');
  });
  it('accepts the downloaded summary in the browser only when its SHA-256 matches the manifest', async () => {
    const def = byId('E02');
    const data = await loadExperiment(def);
    const bytes = await readFile(
      path.join(RESULTS_ROOT, def.id, def.run, 'summary.csv'),
    );
    const rows = await verifySummaryBytes(
      arrayBuffer(bytes),
      data.summarySha,
      data.columns,
      data.rows.length,
    );
    expect(rows).toEqual(data.rows);
    const changed = Buffer.from(bytes);
    changed[changed.length - 2] = changed[changed.length - 2]! ^ 1;
    await expect(
      verifySummaryBytes(
        arrayBuffer(changed),
        data.summarySha,
        data.columns,
        data.rows.length,
      ),
    ).rejects.toThrow(/SHA-256/);
    await expect(
      verifySummaryBytes(
        arrayBuffer(bytes),
        data.summarySha,
        data.columns.slice(1),
        data.rows.length,
      ),
    ).rejects.toThrow(/differs/);
    await expect(
      verifySummaryBytes(
        arrayBuffer(bytes),
        data.summarySha,
        data.columns,
        data.rows.length,
        null,
      ),
    ).rejects.toThrow(/SHA-256/);
  });
  it('summarises the manifest instead of inlining it', async () => {
    const data = await loadExperiment(byId('E01'));
    const summary = manifestSummary(data);
    expect(summary.outputs).toBe(data.manifest.outputs.length);
    expect(summary.bytes).toBe(Buffer.byteLength(data.manifestText));
    expect(summary.sha256).toBe(data.evidence.manifestSha);
    expect(summary.files.map((f) => f.path)).toEqual([
      'summary.csv',
      'paired_contrasts.csv',
    ]);
    expect(JSON.stringify(summary).length).toBeLessThan(5000);
  });
});

describe('p-values', () => {
  it('never shows a stored zero p-value as 0', () => {
    for (const column of ['p', 'p_lower', 'p_upper', 'adjusted_p'])
      expect(isPValueColumn(column)).toBe(true);
    for (const column of ['packet_pdet', 'pdr_mean', 'pair_id'])
      expect(isPValueColumn(column)).toBe(false);
    expect(formatPValue('0.0')).toBe('< numerical resolution');
    expect(formatPValue('0')).toMatch(/^< numerical resolution/);
    expect(formatPValue('0.0', true)).toContain('zero-variance');
    expect(formatPValue('0.0321')).toBe('0.0321');
    expect(formatPValue('')).toBe('undefined');
    const row: Row = { p_lower: '0.0', lo90: '0.0', hi90: '0.0', estimate: '0.0' };
    expect(formatCell(row, 'p_lower')).toContain('zero-variance');
    expect(formatCell(row, 'estimate')).toBe('0.0');
  });
  it('renders E16 p-values and every verdict and loss note without a bare zero p-value', async () => {
    const html = renderToStaticMarkup(
      createElement(ResultsExplorer, await props(e16())),
    );
    // p_lower and p_upper follow hi95 in the E16 table; both are stored as 0.0.
    expect(html).toContain(
      '<td>&lt; numerical resolution (zero-variance branch)</td><td>&lt; numerical resolution (zero-variance branch)</td>',
    );
    const bareZero = /\bp\s*=?\s*0(?:\.0+)?(?![\d.])/;
    for (const def of EXPERIMENTS) {
      const data = await loadExperiment(def);
      const contrasts = data.contrasts?.rows ?? null;
      const v = verdict(def, data.rows, contrasts);
      for (const text of [v.summary, ...v.details]) expect(text).not.toMatch(bareZero);
      for (const c of lossCases(def, data.rows, contrasts))
        expect(c.note).not.toMatch(bareZero);
    }
  });
});

describe('derived verdicts', () => {
  it('E0: pass, and says which checks are external references', async () => {
    const def = byId('E00');
    const data = await loadExperiment(def);
    const v = verdict(def, data.rows);
    expect(v.status).toBe('supported');
    expect(v.summary).toMatch(/^Hypothesis supported \(Pass\)/);
    expect(v.summary).toContain(`all ${data.rows.length} recorded checks`);
    const [external, self, invariant] = v.details;
    for (const name of ['wire_golden_fixed', 'wire_browser', 'wire_ns3', 'wire_wireshark_fields'])
      expect(external).toContain(name);
    expect(self).toContain('wire_python');
    expect(external).not.toContain('wire_python');
    expect(invariant).toContain('gsl_visibility_complete');
    expect(v.details.join(' ')).toMatch(/isl_polar_cutoff cannot fail/);
    expect(v.details.join(' ')).toMatch(/lower bounds/);
    expect(() =>
      verdict(def, [...data.rows, { ...data.rows[0]!, check: 'new_unclassified' }]),
    ).toThrow(/Unclassified/);
    expect(verdict(def, [{ check: 'gsl_degree', violations: '1' }]).summary).toMatch(/Fail/);
  });
  it('E1: not supported for the nominal rate cut and delays, supported for the strong cut; LQ and LS-D caveats', async () => {
    const def = byId('E01');
    const data = await loadExperiment(def);
    const v = verdict(def, data.rows, data.contrasts!.rows);
    expect(v.status).toBe('mixed');
    expect(v.summary).toContain('not supported for the nominal rate cut (factor 0.3)');
    expect(v.summary).toContain('not supported for the added-delay family');
    expect(v.summary).toContain('supported for the strong rate cut (factor 0.2)');
    expect(v.summary).toMatch(/LQ beats ChronoRoute significantly in 13 cells/);
    expect(v.summary).toContain('LS-D comparison is not valid evidence');
    const text = v.details.join('\n');
    // Counts are derived from event_mean × n in the summary (C5 first-third nominal cut: 9 of 36).
    const first = selectRows(def, data.rows, {
      const: 'C5',
      condition: 'rate-0.3-first',
      selected: true,
      k: '2',
    }).find((r) => r['scheme'] === 'chronoroute')!;
    expect(numeric(first['event_mean'])! * 36).toBeCloseTo(9);
    expect(text).toContain('C5 9/36, 0/36, 0/36');
    expect(text).toMatch(/strong 0\.2: C5 36\/36; C2 36\/36 — supported/);
    expect(text).toMatch(/LS-H: 10 significant wins, 5 non-significant wins, 15 ties/);
    expect(text).toMatch(/hold by construction/);
    expect(text).toMatch(/Registered material losses: 61 \(30 detection, 31 restricted delay\); point disadvantages: 82/);
    expect(text).toMatch(/23 adjusted p-values are stored as 0[^\n]*9 from zero-variance/);
    expect(text).toMatch(/LS-D[^\n]*exact injected fault delay/);
    expect(text).toMatch(/above the 1% limit/);
    // The verdict follows the data: if both comparators lost every nominal cell, it would change.
    const allWins = data.contrasts!.rows.map((c) =>
      c['endpoint'] === 'detected' && ['ls_h', 'crh16'].includes(c['comparator']!)
        ? { ...c, mean_diff: '0.5', adjusted_p: '0.001' }
        : c,
    );
    expect(verdict(def, data.rows, allWins).status).toBe('supported');
    const lsd = lossCases(def, data.rows, data.contrasts!.rows).filter(
      (c) => c.competitor === 'ls_d',
    );
    expect(lsd.length).toBeGreaterThan(0);
    expect(lsd.every((c) => c.note.includes('LS-D comparator flaw'))).toBe(true);
    expect(
      lossCases(def, data.rows, data.contrasts!.rows).some((c) =>
        c.note.startsWith('Registered material loss'),
      ),
    ).toBe(true);
  });
  it('E2: derives the CRH-32 crossover from the byte accounting', async () => {
    const def = byId('E02');
    const data = await loadExperiment(def);
    const v = verdict(def, data.rows);
    expect(v.status).toBe('supported');
    expect(v.summary).toContain('CRH-32 is smaller at 1–3, 5, 7 entries');
    expect(v.summary).toContain('more bytes than CRH-16 and fewer than SRv6 SRH at every registered entry count');
    expect(v.details.join(' ')).toMatch(/7 entries\): T-CRH adds 40 bytes, CRH-32 32/);
    expect(ranges([1, 2, 3, 5, 7, 8])).toBe('1–3, 5, 7, 8');
    expect(lossCases(def, data.rows).some((c) => c.competitor === 'crh32')).toBe(true);
  });
  it('E4: mixed, with blackhole loss counts and the tail failure against LS-H', async () => {
    const def = byId('E04');
    const data = await loadExperiment(def);
    const contrasts = data.contrasts!.rows;
    const v = verdict(def, data.rows, contrasts);
    expect(v.status).toBe('mixed');
    expect(v.summary).toMatch(/excludes the fallback’s own hop_limit and loop losses/);
    expect(v.summary).toMatch(/not supported against LS-H/);
    const text = v.details.join('\n');
    expect(text).toMatch(/C2 link-B: blackhole 0 s with 0 counted losses, but 1068 of 216000 packets lost/);
    expect(text).toMatch(/C5 link-B 0\.167 \[0\.0388, 0\.295\]/);
    expect(text).toMatch(/censored in 165 of 165 greedy_visited outages/);
    // PREREG: the loss count is always shown beside blackhole time.
    const cols = def.tableColumns;
    expect(cols.indexOf('blackhole_losses')).toBe(cols.indexOf('blackhole_n') + 1);
    const blackhole = def.metrics.find((m) => m.key === 'blackhole_mean')!;
    expect(blackhole.companions).toEqual(expect.arrayContaining(['blackhole_losses', 'pdr_mean']));
    const html = renderToStaticMarkup(
      createElement(ResultsExplorer, {
        ...(await props(def)),
        definition: { id: def.id, metrics: [blackhole], tableColumns: cols },
      }),
    );
    expect(html).toMatch(/class="result-companions"><li>[^<]*blackhole_losses \d+; pdr_mean/);
    const cases = lossCases(def, data.rows, contrasts).filter((c) => c.metric === 'blackhole_mean');
    expect(cases.length).toBeGreaterThan(0);
    expect(cases.every((c) => c.oursDetail.includes('blackhole_losses') && c.oursDetail.includes('pdr_mean'))).toBe(true);
    // The recovery note names the collector recorded in the manifest.
    const recovery = def.provenance!.find((n) => n.title === 'Recovery')!;
    expect(recovery.commits.map((c) => c.sha)).toContain(data.manifest.git_sha);
    expect(recovery.commits[0]!.sha.startsWith('b805d2d')).toBe(true);
  });
  it('E5: visited beats pure greedy, the Grid detour adds nothing and continue wins C5 completion', async () => {
    const def = byId('E05');
    const data = await loadExperiment(def);
    const v = verdict(def, data.rows, data.contrasts!.rows);
    expect(v.status).toBe('mixed');
    expect(v.summary).toMatch(/reduces the stuck\/loop loss rate against pure greedy in 2 of 2 shells/);
    expect(v.summary).toMatch(/Grid detour shows no extra benefit/);
    expect(v.summary).toMatch(/continue wins triggered completion in C5/);
    expect(v.details.join(' ')).toMatch(/C5 -0\.222 \[-0\.365, -0\.0796\], Holm-adjusted p 0\.00323/);
  });
  it('E16: equivalent within scope, but degenerate and without losses', async () => {
    const def = e16();
    const data = await loadExperiment(def);
    const v = verdict(def, data.rows);
    expect(v.status).toBe('supported');
    expect(v.summary).toMatch(/within the replayed scope/);
    expect(v.summary).toMatch(/degenerate/);
    expect(v.summary).toMatch(/no run lost a packet/);
    expect(v.details.join(' ')).toMatch(/All 144 paired differences are exactly 0/);
    expect(v.details.join(' ')).toMatch(/delivery, queueing and deadline flags/);
    // A non-degenerate equivalence does not claim zero-width intervals.
    const widened = data.rows.map((r) => ({ ...r, lo95: '-0.001', hi95: '0.001' }));
    expect(verdict(def, widened).details.join(' ')).not.toMatch(/exactly 0/);
  });
});

it('fails an actual static build when chart evidence has no manifest', async () => {
  const { spawnSync } = await import('node:child_process');
  const { root, dir } = await fixture();
  const site = path.join(root, 'site');
  await mkdir(path.join(site, 'src/pages'), { recursive: true });
  await symlink(
    path.resolve('node_modules'),
    path.join(site, 'node_modules'),
    'dir',
  );
  await writeFile(
    path.join(site, 'astro.config.mjs'),
    "export default {output:'static',telemetry:false};\n",
  );
  const loader = path.resolve('src/lib/experiments/load.ts');
  const catalog = path.resolve('src/lib/experiments/catalog.ts');
  await writeFile(
    path.join(site, 'src/pages/index.astro'),
    `---\nimport {loadExperiment} from ${JSON.stringify(loader)};\nimport {EXPERIMENTS} from ${JSON.stringify(catalog)};\nconst data=await loadExperiment(EXPERIMENTS.find(e=>e.id==='E16'),${JSON.stringify(root)});\n---\n<html><body><svg role="img"><title>{data.summarySha}</title></svg></body></html>`,
  );
  const cli = path.resolve('node_modules/astro/bin/astro.mjs');
  const build = () =>
    spawnSync(process.execPath, [cli, 'build', '--root', site], {
      cwd: process.cwd(),
      encoding: 'utf8',
      env: { ...process.env, ASTRO_TELEMETRY_DISABLED: '1' },
      timeout: 60000,
    });
  const good = build();
  if (good.status !== 0) throw new Error(good.stdout + good.stderr);
  expect(good.status).toBe(0);
  await rm(path.join(dir, 'manifest.json'));
  const bad = build();
  expect(bad.status).not.toBe(0);
  if (!(bad.stdout + bad.stderr).includes('manifest.json'))
    throw new Error(
      JSON.stringify({
        status: bad.status,
        error: bad.error?.message,
        signal: bad.signal,
        stdout: bad.stdout,
        stderr: bad.stderr,
      }),
    );
}, 120000);

it('links the experiments index and rebuilds when result releases change', async () => {
  const { NAV_ITEMS } = await import('../src/lib/site');
  expect(NAV_ITEMS.some((item) => item.path === 'experiments')).toBe(true);
  expect(
    await readFile(path.resolve('../.github/workflows/pages.yml'), 'utf8'),
  ).toContain('"results/**"');
});

it('serves the same CSV, manifest and paired contrasts through each static download endpoint', async () => {
  const endpoint = await import('../src/pages/experiments/[experiment]/[file]');
  const paths = await endpoint.getStaticPaths();
  expect(paths).toHaveLength(
    EXPERIMENTS.length * 2 + EXPERIMENTS.filter((e) => e.contrasts).length,
  );
  expect(paths.map((p) => `${p.params.experiment}/${p.params.file}`)).toContain(
    'e4/paired_contrasts.csv',
  );
  for (const entry of paths) {
    const def = EXPERIMENTS.find((e) => e.slug === entry.params.experiment)!;
    const response = await endpoint.GET({
      props: entry.props,
    } as unknown as Parameters<typeof endpoint.GET>[0]);
    const source = await readFile(
      path.join(RESULTS_ROOT, def.id, def.run, entry.params.file),
    );
    expect(Buffer.from(await response.arrayBuffer()).equals(source)).toBe(true);
  }
});

it('keeps failed constraints and infinite-tail disadvantages in the verdict', () => {
  const e0 = EXPERIMENTS.find((e) => e.id === 'E00')!;
  expect(verdict(e0, [{ violations: '1' }]).summary).toMatch(/Fail/);
  const e1 = EXPERIMENTS.find((e) => e.id === 'E01')!;
  const failed = verdict(e1, [
    { scheme: 'chronoroute', selected: 'True', k: '2', fpr: '0.02' },
  ]);
  expect(failed.status).toBe('not supported');
  expect(failed.summary).toMatch(/fails/);
  expect(
    verdict(e1, [
      { scheme: 'chronoroute', selected: 'True', k: '2', fpr: '0.001' },
    ]).summary,
  ).toMatch(/meets/);
  const e4 = EXPERIMENTS.find((e) => e.id === 'E04')!;
  const bad = lossCases(e4, [
    {
      const: 'C5',
      condition: 'node-B',
      scheme: 'greedy_visited',
      effective_p99_mean: 'inf',
    },
    {
      const: 'C5',
      condition: 'node-B',
      scheme: 'snap',
      effective_p99_mean: '0.1',
    },
  ]);
  expect(bad).toHaveLength(1);
  expect(bad[0]?.ours).toBe('inf');
});

it('rejects mislabelled network data and malformed source commits', async () => {
  const { root, dir } = await fixture();
  const file = path.join(dir, 'manifest.json');
  const original = JSON.parse(await readFile(file, 'utf8'));
  for (const change of [
    (m: any) => {
      m.git_sha = '_'.repeat(40);
    },
    (m: any) => {
      m.labels.traffic_probes = 'REAL';
    },
  ]) {
    const m = structuredClone(original);
    change(m);
    await writeFile(file, JSON.stringify(m));
    await expect(loadExperiment(e16(), root)).rejects.toThrow();
  }
});

it('does not call an undefined operating constraint a pass', () => {
  const def = EXPERIMENTS.find((e) => e.id === 'E01')!;
  expect(
    verdict(def, [
      { scheme: 'chronoroute', selected: 'True', k: '2', fpr: '' },
    ]).summary,
  ).toMatch(/unestablished|undefined/i);
  expect(
    verdict(def, [{ scheme: 'lq', selected: 'True', k: '2', fpr: '0' }]).status,
  ).toBe('unestablished');
});

it('places axis labels at their data coordinates, including an exact zero series', () => {
  const model = chartModel([{ violations: '0' }], {
    key: 'violations',
    label: 'Violations',
    unit: 'count',
  });
  expect(model.ticks).toHaveLength(1);
  expect(model.ticks[0]?.value).toBe(0);
  expect(model.ticks[0]?.y).toBe(model.points[0]?.y);
  const intervals = chartModel([{ mean: '1', lo: '0.8', hi: '1.2' }], {
    key: 'mean',
    lo: 'lo',
    hi: 'hi',
    label: 'CI',
    unit: 'ratio',
  });
  expect(intervals.ticks[0]?.y).toBe(intervals.points[0]?.lowY);
  expect(intervals.ticks[1]?.y).toBe(intervals.points[0]?.highY);
});

it('refuses to render a chart without a verified manifest reference', async () => {
  const { evidence, ...rest } = await props(e16());
  expect(evidence.dirty).toBe(false);
  expect(() =>
    renderToStaticMarkup(
      createElement(
        ResultsExplorer,
        rest as unknown as Parameters<typeof ResultsExplorer>[0],
      ),
    ),
  ).toThrow(/manifest/);
  expect(() =>
    renderToStaticMarkup(
      createElement(ResultsExplorer, {
        ...rest,
        evidence: { ...evidence, dirty: true } as unknown as typeof evidence,
      }),
    ),
  ).toThrow(/manifest/);
});
