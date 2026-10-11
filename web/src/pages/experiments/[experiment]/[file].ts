import type { APIRoute } from 'astro';
import { EXPERIMENTS } from '../../../lib/experiments/catalog';
import { loadExperiment } from '../../../lib/experiments/load';
/** Byte-preserving downloads use exactly the evidence read by the page and its chart. */
export async function getStaticPaths() {
  return (
    await Promise.all(
      EXPERIMENTS.map(async (def) => {
        const data = await loadExperiment(def);
        return [
          {
            params: { experiment: def.slug, file: 'summary.csv' },
            props: { text: data.csvText, type: 'text/csv; charset=utf-8' },
          },
          {
            params: { experiment: def.slug, file: 'manifest.json' },
            props: {
              text: data.manifestText,
              type: 'application/json; charset=utf-8',
            },
          },
        ];
      }),
    )
  ).flat();
}
export const GET: APIRoute = ({ props }) =>
  new Response(props['text'] as string, {
    headers: { 'Content-Type': props['type'] as string },
  });
