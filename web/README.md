# ChronoRoute website

The public website of ChronoRoute: deadline-based source routing (T-CRH) for LEO satellite
constellations. A static Astro site in the `web/` folder of the ChronoRoute repository,
published to GitHub Pages at <https://aeehprrst.github.io/chronoroute/> by
`.github/workflows/pages.yml` and refreshed with new orbit data every 4 hours by
`.github/workflows/refresh-data.yml`.

## The honesty rule

Every number and visual is labelled **REAL**, **DERIVED**, **MODELLED** or **UNKNOWN**. The
labels come from the project's one shared table, `sim/chronoroute/labels.py` (mirrored in
`src/lib/label-keys.ts`, checked by `tests/label-keys.test.ts`):

* **REAL**: public or measured data, real physics computed by real code on REAL inputs, or the
  exact output of our code (CelesTrak elements, SGP4 positions, city coordinates, T-CRH bytes).
* **DERIVED**: computed by our code from REAL inputs by an inference or choice that could be made
  differently (shells and orbital planes, colour groups, routes and their budgets).
* **MODELLED**: our assumption, because the truth is not public (laser links, ground-link
  assignment, processing delay, traffic, failures).
* **UNKNOWN**: Starlink's real routing; never claimed, and Starlink does not use T-CRH.

No placeholder or invented numbers. If the data for a section does not exist yet, use
`BuildingState` with `phase="results"` and say so. Result numbers are never copied into the site
by hand: link to the result files. Not affiliated with SpaceX: no SpaceX or Starlink logos.

## Commands

All commands run inside WSL from this folder, with the Linux Node.js:

```sh
export PATH=$HOME/.local/opt/node/bin:$PATH   # Node 24, npm 11
npm ci                 # install exactly what package-lock.json pins
npm run data           # public/data/ + .parity/ (+ .parity/served/) from the Python pipeline (needs ../venv)
npm run dev            # dev server: http://localhost:4321/chronoroute/
npm run build          # static site in dist/
npm run preview        # serve dist/ at http://localhost:4321/chronoroute/
npm run check          # astro check (TypeScript 6, strictest settings)
npm test               # vitest (needs `npm run data` first)
npm run data:offline-fallback   # ONLY without Python: globe data from dev-data.mjs (no route planner)
```

Astro's anonymous telemetry is switched off in every npm script (`ASTRO_TELEMETRY_DISABLED=1`)
and in the workflows.

`npm run data` runs `scripts/build-data.sh [SNAPSHOT_DIR]` (default: the newest
`../data/pinned/*-celestrak`): `cr export web` (snapshot, `shells.json`, `isl_grid4.json`),
`pipeline/validate.py --web`, verbatim copies of `../data/static/cities.csv` and
`sid_registry.json` into `public/data/static/`, and `tools/web_parity.py` twice: the reference
snapshot into `.parity/` and the published snapshot into `.parity/served/`. Set
`PYTHON=...` to use another interpreter than `../venv/bin/python`. `public/data/` and `.parity/`
are generated and git-ignored.

## Layout

```
astro.config.mjs        site + base ('/chronoroute'), static output, React, sitemap
DATA_CONTRACT.md        the format of public/data (read before producing data)
scripts/build-data.sh   public/data + .parity from the Python pipeline (npm run data; used by CI)
scripts/newest-snapshot.sh  newest pinned SupGP snapshot in the given folders (--all: all, newest first)
scripts/build-tested-data.sh  pages.yml: newest snapshot that passes build-data + npm test, else older ones
scripts/dev-data.mjs    OFFLINE FALLBACK only: pinned snapshot -> the three snapshot files
scripts/sgp4-crosscheck.mjs  prints satellite.js positions for a manual comparison with Python
public/data/            generated, git-ignored (see DATA_CONTRACT.md)
.parity/                generated, git-ignored: Python reference routes (tools/web_parity.py);
                        .parity/served/ = the same for the published snapshot
src/layouts/BaseLayout.astro
src/components/         SiteHeader, SiteFooter, LabelChip, DataBadge, BuildingState, HeaderBytes
src/components/globe/   the 3D globes (GlobeIsland, GlobeCanvas, engine, styles)
src/components/protocol/ protocol tools (byte map, builder, decoder, stepper, sizes, home diagram)
src/components/route/   the route planner island (RoutePlanner.tsx, route.css)
src/engine/             TypeScript port of the T-CRH/CRH reference (checked on the golden vectors)
  packet.ts             IPv6 + T-CRH + UDP packet and pcap writer (port of chronoroute.trace.pcap)
src/workers/            orbit.worker.ts: SGP4 off the main thread (Float32 frames for the globe,
                        Float64 TEME positions for the route planner)
src/lib/orbit/          orbit maths: frames, Sun, propagation, clock, colour groups
src/lib/route/          the route planner's core, a port of the Python router:
  geometry.ts           WGS84, elevation, 80 km grazing test, light time (numpy's arithmetic order)
  topology.ts           shells.json / isl_grid4.json, link states at an instant, ground links, CSR graph
  dijkstra.ts           binary heap, lowest-node-id tie-break (route/dijkstra.py)
  planner.ts            path -> budgets -> T-CRH -> packet -> pcap (route/scheduler.py)
  cities.ts, sids.ts    cities.csv and the SID registry readers
  context.ts, frame.ts, load.ts  per-snapshot context, SGP4 frame -> ECEF, browser loader
  parity-summary.ts     public/data/parity.json: type, validator and the parity badge's wording
src/lib/label-keys.ts   the shared label table (copy of sim/chronoroute/labels.py)
  paths.ts              base-path helpers: pageHref(), assetHref(), dataHref()
  data-types.ts         TypeScript types of the snapshot part of the data contract
  data.ts               validators + browser loader (loadLatestSnapshot)
  data-build.ts         build-time readers (Node only): snapshot manifest, golden vectors
  labels.ts             the four provenance labels and their definitions
  site.ts               site name, repository URL, navigation (only pages that exist)
  tcrh-layout.ts        splits T-CRH bytes into spec fields (display only; tested on golden vectors)
  format.ts             UTC/age/integer formatting
src/styles/tokens.css   design tokens (palette, type scale, spacing)
src/styles/global.css   base styles and utilities
src/pages/              index, live, route, protocol, methodology, about, 404
tests/                  vitest tests, including route-parity (+ parity-gate.ts, the rule), parity-gate,
                        parity-summary, sgp4-parity, label-keys, data-contract, ci-scripts
```

## Route parity (the deploy gate)

`../tools/web_parity.py` makes the Python router compute 20 canonical city pairs at a pinned
snapshot's download time and exports the positions it used (every satellite of the shell and
every city of the pairs). `scripts/build-data.sh` runs it twice: on the reference snapshot
`data/pinned/20261010T1358Z-celestrak` (2026-10-10T14:02:22Z), a fixed yardstick, and on the
snapshot being published, so the gate also covers the data actually served.
`tests/route-parity.test.ts` runs the TypeScript planner on Python's positions for both: the
reference run on the inputs embedded in the parity file, the served run on the published files
in `public/data` (after checking that they come from the same download: `sha256_raw`, time and
source).

The rule (`tests/parity-gate.ts`, itself tested by `tests/parity-gate.test.ts`): a pair fails,
and the deploy is blocked, only when its path cost differs by more than 1 ns or a byte of the
T-CRH template, the per-packet T-CRH, the packet or the pcap differs. On a genuine tie (cost
within 1 ns, different path) the same bytes are rebuilt from Python's path with the planner's
own `pathBytes` and compared; the pair is counted as a tie, never as an identical path. Laser
links up/down, visible and connected satellites and per-hop delays are compared and printed as
diagnostics. City positions come from Python because V8's `Math.sin`/`Math.cos` can differ
from numpy's in the last bit (5 of the 60 cities differ by one ulp in one coordinate); our own
conversion is checked separately, within 1e-9 km. `tests/sgp4-parity.test.ts` compares
satellite.js with python-sgp4 for every satellite of the shell in both snapshots, using the
published element sets for the served check: at most 10 m, and at most 1 m
once EPOCH is cut to milliseconds (satellite.js reads EPOCH through a JavaScript Date, which
keeps milliseconds only). CI writes the result summary to `public/data/parity.json`
(`src/lib/route/parity-summary.ts`), which the route page shows; it says "identical" only
when every path was.

`pages.yml` builds the data with `scripts/build-tested-data.sh`: the newest snapshot (committed
or downloaded by `refresh-data.yml`) that passes `build-data.sh` and `npm test`, falling back to
at most two older ones with a warning on the run, so one bad download cannot freeze the site
for every code push. A code defect fails every candidate, and then nothing is deployed.

The route planner picks the Grid-4 laser-link pairs from `isl_grid4.json`, i.e. those Python
chose at the snapshot's download time, and evaluates their up/down state at the chosen instant.
`cr route --at T` chooses the pairs at T instead, so the two agree exactly at the snapshot time
(which is what the parity test checks) and may differ hours later.

## Rules for contributors

* **Base path.** Never write `href="/..."`. Use `pageHref('protocol')`,
  `pageHref('methodology#labels')`, `assetHref('favicon.svg')` or `dataHref('latest.json')`
  from `src/lib/paths.ts`. Pages always end in `/` (`trailingSlash: 'always'`).
* **Navigation.** Add a page to `NAV_ITEMS` in `src/lib/site.ts` only when the page exists.
* **Spec.** The normative protocol is `../spec/tcrh-v1.md`; golden vectors are in
  `../spec/golden/`. Read them with paths relative to this folder (`../spec/...`, inside the
  repository). Never write into `../spec` or `../data`.
* **Parity.** Any change to the route planner's arithmetic (`src/lib/route/`) must keep
  `tests/route-parity.test.ts` green; change the Python router and the port in the same commit.
* **No third-party requests at runtime.** Fonts are self-hosted via @fontsource; data comes
  from `public/data`. No analytics, no cookies.
* **Colour.** Use the tokens. `--deadline` (amber) is reserved for timing and deadline
  concepts. Labels always use `LabelChip` (colour plus shape); the React islands use the same
  markup (`rp-chip` in `route.css`).
* **Accessibility.** Semantic landmarks and headings, visible focus, text alternatives for every
  visualisation, `prefers-reduced-motion` respected, no horizontal scroll at 375 px.

## Dependencies

Exact versions (no `^`/`~`); `.npmrc` sets `save-exact=true`. Every direct dependency was
checked to be published before 2026-09-26, and the lockfile was resolved with
`npm install --before=2026-09-26T00:00:00Z`, so transitive packages are also from before that
date. The route planner added no dependency.

## Known issues

* **Console warning.** Each globe mount logs `THREE.Clock: This module has been deprecated.
  Please use THREE.Timer instead.` twice. It comes from @react-three/fiber 9.8.1 on three
  0.186, not from site code, and is harmless. Update @react-three/fiber once a release that
  uses `THREE.Timer` is at least two weeks old.
* **Touch screens, live globe.** A swipe over the globe scrolls the page; the reader turns on
  "Move globe" (below the globe on phones, over its top-right corner on wider screens) to rotate
  and pinch-zoom it with a finger. Taps still select satellites. The small home-page globe has
  no controls and never blocks scrolling.
* **npm install-scripts warning.** `npm ci` reports that esbuild's postinstall script is not
  covered by `allowScripts`; the build and the tests work without it (measured 2026-10-11).

`npm audit` (2026-10-10) reports three high-severity advisories, all in build-time transitive
dependencies that are never shipped to the browser: `sharp` 0.35.4 (via astro; fixed in
0.35.5, published 2026-09-27), `source-map-js` 1.2.1 (fixed in 1.2.2, 2026-09-30) and
`http-cache-semantics` 4.2.0 (fixed in 4.3.0, 2026-10-04). The fixes are newer than the
two-week rule allows today. Run `npm audit fix` once each fix is at least two weeks old
(after 2026-10-11, 2026-10-14 and 2026-10-18 respectively), then rebuild and re-test.
