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
import { EXPERIMENTS } from '../src/lib/experiments/catalog';
import { loadExperiment, RESULTS_ROOT } from '../src/lib/experiments/load';
import {
  parseCsv,
  numeric,
  formatValue,
  selectRows,
  chartModel,
  lossCases,
  verdict,
} from '../src/lib/experiments/data';
import ResultsExplorer from '../src/components/experiments/ResultsExplorer';

const scratch: string[] = [];
afterEach(async () => {
  await Promise.all(
    scratch.splice(0).map((p) => rm(p, { recursive: true, force: true })),
  );
});
const e16 = () => EXPERIMENTS.find((e) => e.id === 'E16')!;

async function fixture() {
  const root = await mkdtemp(path.join(os.tmpdir(), 'experiment-site-'));
  scratch.push(root);
  const dir = path.join(root, e16().id, e16().run);
  await mkdir(dir, { recursive: true });
  for (const name of ['summary.csv', 'manifest.json'])
    await writeFile(
      path.join(dir, name),
      await readFile(path.join(RESULTS_ROOT, e16().id, e16().run, name)),
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
      expect(verdict(def, data.rows)).not.toBe('');
    }
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
    expect(verdict(e5, five.rows)).toMatch(/unsupported|mixed|Mixed/);
    expect(verdict(e16(), [{ complete: 'True', equivalent: 'False' }])).toMatch(
      /unestablished/,
    );
  });
  it('server-renders usable charts and a data table without JavaScript, with safe escaped content', async () => {
    const data = await loadExperiment(e16());
    const html = renderToStaticMarkup(
      createElement(ResultsExplorer, {
        definition: e16(),
        rows: data.rows,
        columns: data.columns,
        evidence: data.evidence,
      }),
    );
    expect(html).toContain('<svg');
    expect(html).toContain('confidence');
    expect(html).toContain('<table');
    expect(html).not.toContain('NaN');
    // Every SVG tooltip carries text (an array child renders an empty <title> in React 19).
    expect(html).toContain('<title>');
    expect(html).not.toContain('<title></title>');
    const injected = renderToStaticMarkup(
      createElement(ResultsExplorer, {
        definition: e16(),
        rows: [{ ...data.rows[0], condition: '<script>bad()</script>' }],
        columns: data.columns,
        evidence: data.evidence,
      }),
    );
    expect(injected).not.toContain('<script>bad()');
    expect(injected).toContain('&lt;script&gt;');
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

it('serves the same CSV and manifest through each static download endpoint', async () => {
  const endpoint = await import('../src/pages/experiments/[experiment]/[file]');
  const paths = await endpoint.getStaticPaths();
  expect(paths).toHaveLength(EXPERIMENTS.length * 2);
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
  expect(verdict(e0, [{ violations: '1' }])).toMatch(/Fail/);
  const e1 = EXPERIMENTS.find((e) => e.id === 'E01')!;
  expect(
    verdict(e1, [
      { scheme: 'chronoroute', selected: 'True', k: '2', fpr: '0.02' },
    ]),
  ).toMatch(/fails/);
  expect(
    verdict(e1, [
      { scheme: 'chronoroute', selected: 'True', k: '2', fpr: '0.001' },
    ]),
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
    ]),
  ).toMatch(/unestablished/);
  expect(
    verdict(def, [{ scheme: 'lq', selected: 'True', k: '2', fpr: '0' }]),
  ).toMatch(/unestablished/);
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
  const data = await loadExperiment(e16());
  expect(() =>
    renderToStaticMarkup(
      createElement(ResultsExplorer, {
        definition: e16(),
        rows: data.rows,
        columns: data.columns,
      } as unknown as Parameters<typeof ResultsExplorer>[0]),
    ),
  ).toThrow(/manifest/);
});
