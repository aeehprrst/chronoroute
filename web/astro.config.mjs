// @ts-check
import { defineConfig } from 'astro/config';
import react from '@astrojs/react';
import sitemap from '@astrojs/sitemap';

/** Public origin of the GitHub Pages site. */
export const SITE = 'https://aeehprrst.github.io';
/** Every page and asset lives under this path (https://aeehprrst.github.io/chronoroute/). */
export const BASE = '/chronoroute';

export default defineConfig({
  site: SITE,
  base: BASE,
  output: 'static',
  // GitHub Pages serves /chronoroute/live/ (directory index); links always carry the slash.
  // With 'always', import.meta.env.BASE_URL is '/chronoroute/'.
  trailingSlash: 'always',
  build: {
    format: 'directory',
  },
  // HTML compression removes the line-break whitespace before inline links in prose
  // ("in the<a ...>"), so it is turned off.
  compressHTML: false,
  integrations: [
    react(),
    sitemap({
      filter: (page) => !/\/404\/?$/.test(new URL(page).pathname),
    }),
  ],
  devToolbar: {
    enabled: false,
  },
});
