/**
 * Formatting helpers for times and ages. Pure functions with no locale dependence, so
 * the server-rendered HTML and the browser agree.
 */

/**
 * Parse an ISO 8601 UTC timestamp. CelesTrak EPOCH strings carry no zone
 * ("2026-10-10T11:09:41.999962"); they are UTC, so a missing zone is read as "Z".
 * Returns milliseconds since 1970 or NaN.
 */
export function parseUtc(iso: string): number {
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(iso);
  return Date.parse(hasZone ? iso : `${iso}Z`);
}

/** "2026-10-10 14:02:22 UTC" (truncated to whole seconds). Returns the input unchanged if it cannot be parsed. */
export function formatUtc(iso: string, precision: 'seconds' | 'minutes' = 'seconds'): string {
  const ms = parseUtc(iso);
  if (Number.isNaN(ms)) return iso;
  const text = new Date(ms).toISOString(); // YYYY-MM-DDTHH:MM:SS.sssZ
  const length = precision === 'seconds' ? 19 : 16;
  return `${text.slice(0, 10)} ${text.slice(11, length)} UTC`;
}

/**
 * Human age of a timestamp relative to `nowMs`, e.g. "3 h 12 min", "2 d 4 h", "45 s".
 * Negative ages (timestamp in the future) are returned with a leading "in ".
 */
export function formatAge(fromMs: number, nowMs: number): string {
  if (!Number.isFinite(fromMs) || !Number.isFinite(nowMs)) return '';
  const diff = nowMs - fromMs;
  const future = diff < 0;
  const totalSeconds = Math.floor(Math.abs(diff) / 1000);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  let text: string;
  if (days > 0) text = hours > 0 ? `${days} d ${hours} h` : `${days} d`;
  else if (hours > 0) text = minutes > 0 ? `${hours} h ${minutes} min` : `${hours} h`;
  else if (minutes > 0) text = `${minutes} min`;
  else text = `${seconds} s`;
  return future ? `in ${text}` : text;
}

/** Integer with comma thousands separators ("11,130"), locale independent. */
export function formatInt(value: number): string {
  return Math.trunc(value)
    .toString()
    .replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}
