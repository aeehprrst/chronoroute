/**
 * Base-path helpers. The site is served from https://aeehprrst.github.io/chronoroute/,
 * so every internal link and asset URL must start with the base path. Never write
 * href="/protocol/" by hand; use pageHref('protocol').
 *
 * The pure functions take the base as an argument so they can be tested; the short
 * forms use import.meta.env.BASE_URL ('/chronoroute/' with trailingSlash: 'always').
 */

/** The configured base path, always with a leading and trailing slash. */
export const BASE_URL: string = normaliseBase(import.meta.env.BASE_URL ?? '/');

/** Ensure a base path has exactly one leading and one trailing slash ('' and '/' become '/'). */
export function normaliseBase(base: string): string {
  const trimmed = base.replace(/^\/+|\/+$/g, '');
  return trimmed === '' ? '/' : `/${trimmed}/`;
}

/** Split "path?query#hash" into its three parts. */
function splitSuffix(path: string): { pathname: string; suffix: string } {
  const index = path.search(/[?#]/);
  return index === -1
    ? { pathname: path, suffix: '' }
    : { pathname: path.slice(0, index), suffix: path.slice(index) };
}

/**
 * Join a base path and a file path ('data/latest.json'). Leading slashes on the path are
 * ignored, so the result can never escape the base.
 */
export function joinBase(base: string, path: string): string {
  return normaliseBase(base) + path.replace(/^\/+/, '');
}

/**
 * URL of a page: always ends in a slash before any query or hash, to match
 * trailingSlash: 'always' and GitHub Pages directory indexes.
 * pageHref('') -> '/chronoroute/', pageHref('methodology#labels') -> '/chronoroute/methodology/#labels'.
 */
export function pageHrefFor(base: string, path: string): string {
  const { pathname, suffix } = splitSuffix(path);
  const clean = pathname.replace(/^\/+|\/+$/g, '');
  return normaliseBase(base) + (clean === '' ? '' : `${clean}/`) + suffix;
}

/** True when `currentPathname` is the page `href` points to (ignores trailing slashes, query and hash). */
export function isCurrentPage(currentPathname: string, href: string): boolean {
  const strip = (value: string) => splitSuffix(value).pathname.replace(/\/+$/, '') || '/';
  return strip(currentPathname) === strip(href);
}

/** Page URL under the configured base. */
export function pageHref(path: string): string {
  return pageHrefFor(BASE_URL, path);
}

/** Asset or file URL under the configured base (no trailing slash added). */
export function assetHref(path: string): string {
  return joinBase(BASE_URL, path);
}

/** URL of a file under public/data/, e.g. dataHref('latest.json') -> '/chronoroute/data/latest.json'. */
export function dataHref(path: string): string {
  return joinBase(BASE_URL, `data/${path.replace(/^\/+/, '')}`);
}
