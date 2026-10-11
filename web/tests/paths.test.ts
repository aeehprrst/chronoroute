import { describe, expect, it } from 'vitest';
import { isCurrentPage, joinBase, normaliseBase, pageHrefFor } from '../src/lib/paths';
import config, { BASE } from '../astro.config.mjs';

describe('normaliseBase', () => {
  it('adds exactly one leading and trailing slash', () => {
    expect(normaliseBase('/chronoroute')).toBe('/chronoroute/');
    expect(normaliseBase('chronoroute/')).toBe('/chronoroute/');
    expect(normaliseBase('//chronoroute//')).toBe('/chronoroute/');
    expect(normaliseBase('/')).toBe('/');
    expect(normaliseBase('')).toBe('/');
  });
});

describe('joinBase', () => {
  it('joins files under the base and never escapes it with a leading slash', () => {
    expect(joinBase('/chronoroute/', 'data/latest.json')).toBe('/chronoroute/data/latest.json');
    expect(joinBase('/chronoroute', '/favicon.svg')).toBe('/chronoroute/favicon.svg');
    expect(joinBase('/', 'favicon.svg')).toBe('/favicon.svg');
  });
});

describe('pageHrefFor', () => {
  it('gives every page a trailing slash, before any hash or query', () => {
    expect(pageHrefFor('/chronoroute/', '')).toBe('/chronoroute/');
    expect(pageHrefFor('/chronoroute/', 'live')).toBe('/chronoroute/live/');
    expect(pageHrefFor('/chronoroute/', '/protocol/')).toBe('/chronoroute/protocol/');
    expect(pageHrefFor('/chronoroute/', 'methodology#labels')).toBe('/chronoroute/methodology/#labels');
    expect(pageHrefFor('/chronoroute/', 'live?t=0')).toBe('/chronoroute/live/?t=0');
    expect(pageHrefFor('/', 'about')).toBe('/about/');
  });
});

describe('isCurrentPage', () => {
  it('matches with or without the trailing slash and ignores the hash', () => {
    expect(isCurrentPage('/chronoroute/live/', '/chronoroute/live/')).toBe(true);
    expect(isCurrentPage('/chronoroute/live', '/chronoroute/live/')).toBe(true);
    expect(isCurrentPage('/chronoroute/', '/chronoroute/')).toBe(true);
    expect(isCurrentPage('/chronoroute/methodology/', '/chronoroute/methodology/#labels')).toBe(true);
    expect(isCurrentPage('/chronoroute/live/', '/chronoroute/')).toBe(false);
  });
});

describe('astro.config.mjs', () => {
  it('serves the site from https://aeehprrst.github.io/chronoroute/', () => {
    expect(config.site).toBe('https://aeehprrst.github.io');
    expect(config.base).toBe('/chronoroute');
    expect(BASE).toBe('/chronoroute');
    expect(config.trailingSlash).toBe('always');
    expect(config.output).toBe('static');
    expect(pageHrefFor(config.base ?? '/', 'live')).toBe('/chronoroute/live/');
  });
});
