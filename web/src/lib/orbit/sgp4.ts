/**
 * The satellite.js functions the globe uses, imported from the library's own module files.
 *
 * Why not `import { ... } from 'satellite.js'`: the package root also re-exports its WebAssembly
 * bulk propagator, whose loader uses top-level await. Vite bundles Web Workers as classic
 * (iife) scripts by default, which cannot contain top-level await, so the worker build fails
 * as soon as the root entry is imported. The package's "exports" map exposes only the root, so
 * the module files are referenced by path inside web/node_modules (exact version pinned in
 * package.json and package-lock.json). sgp4.test.ts checks that each function here is the very
 * same function object that the package root exports.
 *
 * The alternative is `vite: { worker: { format: 'es' } }` in astro.config.mjs (see the globe
 * owner's REQUESTS); then these could be plain 'satellite.js' imports again.
 */
export { json2satrec } from '../../../node_modules/satellite.js/dist/io.js';
export { propagate } from '../../../node_modules/satellite.js/dist/propagation/propagate.js';
export { gstime } from '../../../node_modules/satellite.js/dist/propagation/gstime.js';
export { eciToGeodetic, geodeticToEcf } from '../../../node_modules/satellite.js/dist/transforms.js';
export type { SatRec } from '../../../node_modules/satellite.js/dist/propagation/SatRec.js';
