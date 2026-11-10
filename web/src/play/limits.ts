/**
 * How many characters each way of speaking takes (DEL-154, audit finding 7), as the server enforces them
 * (`delve.web.play_limits`; a test there reads this file, so keep one `name: number` per line). The composer stops
 * typing past its channel's length and counts down near it.
 */
export const LIMITS = {
  act: 4000,
  ask: 2000,
  talk: 1500,
  hint: 500,
} as const;

/** The counter shows once the words pass this share of their channel's length. */
export const COUNT_FROM = 0.8;
