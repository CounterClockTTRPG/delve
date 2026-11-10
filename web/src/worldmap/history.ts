/** The editor keeps this many states: the current one and 99 to undo. */
export const MAX_STATES = 100;

/**
 * Undo and redo over whole states, pure: every step answers a new `History` and leaves this one as it was, so it can
 * sit in React state. A push after an undo drops what could have been redone.
 */
export class History<T> {
  private constructor(
    private readonly past: readonly T[],
    readonly current: T,
    private readonly future: readonly T[],
  ) {}

  static of<T>(state: T): History<T> {
    return new History<T>([], state, []);
  }

  get canUndo(): boolean {
    return this.past.length > 0;
  }

  get canRedo(): boolean {
    return this.future.length > 0;
  }

  push(state: T): History<T> {
    const past = [...this.past, this.current];
    return new History(past.slice(Math.max(0, past.length - (MAX_STATES - 1))), state, []);
  }

  undo(): History<T> {
    if (!this.canUndo) return this;
    return new History(this.past.slice(0, -1), this.past[this.past.length - 1], [this.current, ...this.future]);
  }

  redo(): History<T> {
    if (!this.canRedo) return this;
    return new History([...this.past, this.current], this.future[0], this.future.slice(1));
  }
}
