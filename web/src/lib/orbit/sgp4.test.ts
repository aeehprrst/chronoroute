/**
 * src/lib/orbit/sgp4.ts must re-export exactly the functions of the installed satellite.js.
 */
import { describe, expect, it } from 'vitest';
import * as root from 'satellite.js';
import * as local from './sgp4';

describe('sgp4.ts re-exports', () => {
  it('are the same function objects as the satellite.js package root exports', () => {
    expect(local.json2satrec).toBe(root.json2satrec);
    expect(local.propagate).toBe(root.propagate);
    expect(local.gstime).toBe(root.gstime);
    expect(local.eciToGeodetic).toBe(root.eciToGeodetic);
    expect(local.geodeticToEcf).toBe(root.geodeticToEcf);
  });
});
