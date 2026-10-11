/**
 * The simulated clock of the globe. Pure functions, so the behaviour is testable.
 *
 * Simulated time advances at `speed` times real time from an anchor:
 *     sim(real) = anchorSimMs + (real - anchorRealMs) * speed
 * Every control action (speed change, jump, scrub) re-anchors the clock at the current
 * instant, so the simulated time never jumps unless the user asks for a jump.
 */

export type Speed = 0 | 1 | 60 | 600;

/** Speed buttons in display order (0 = paused). */
export const SPEEDS: readonly Speed[] = [0, 1, 60, 600];

export interface ClockState {
  anchorSimMs: number;
  anchorRealMs: number;
  speed: Speed;
}

/** Half-width of the scrub slider (6 hours). */
export const SCRUB_RANGE_MS = 6 * 3_600_000;

export function createClock(simMs: number, realMs: number, speed: Speed): ClockState {
  return { anchorSimMs: simMs, anchorRealMs: realMs, speed };
}

/** Simulated Unix time (ms) at real time `realMs`. */
export function simTimeAt(state: ClockState, realMs: number): number {
  return state.anchorSimMs + (realMs - state.anchorRealMs) * state.speed;
}

/** Change speed without moving the simulated time. */
export function withSpeed(state: ClockState, realMs: number, speed: Speed): ClockState {
  return { anchorSimMs: simTimeAt(state, realMs), anchorRealMs: realMs, speed };
}

/** Jump to a simulated time, keeping the speed. */
export function jumpTo(state: ClockState, realMs: number, simMs: number): ClockState {
  return { anchorSimMs: simMs, anchorRealMs: realMs, speed: state.speed };
}

/** Clamp a scrub offset (ms) to the slider range. */
export function clampScrub(offsetMs: number): number {
  return Math.max(-SCRUB_RANGE_MS, Math.min(SCRUB_RANGE_MS, offsetMs));
}

/** "×60" style label; "Paused" for 0. */
export function speedLabel(speed: Speed): string {
  return speed === 0 ? 'Paused' : `×${speed}`;
}
