import { expect, it } from 'vitest';
import { initialPlayback, playbackReducer } from './playback';

it('starts from the first saved fact and stops at the captured end', () => {
  let state = playbackReducer(initialPlayback, { type: 'toggle', head: 3 });
  expect(state).toMatchObject({ mode: 'history', cursor: 1, boundary: 3, playing: true });
  state = playbackReducer(state, { type: 'tick' });
  expect(state.cursor).toBe(2);
  state = playbackReducer(state, { type: 'tick' });
  expect(state).toMatchObject({ cursor: 3, playing: false });
});

it('does not let incoming live events change a history boundary', () => {
  let state = playbackReducer(initialPlayback, { type: 'seek', cursor: 1, head: 3 });
  state = playbackReducer(state, { type: 'seek', cursor: 99, head: 99 });
  expect(state).toMatchObject({ cursor: 3, boundary: 3 });
  state = playbackReducer(state, { type: 'follow' });
  expect(state.mode).toBe('follow');
  state = playbackReducer(state, { type: 'step', delta: -1, head: 99 });
  expect(state).toMatchObject({ cursor: 98, boundary: 99 });
});

it('pauses stepping, clamps selection and retains the speed on return to latest', () => {
  let state = playbackReducer(initialPlayback, { type: 'toggle', head: 14 });
  state = playbackReducer(state, { type: 'speed', speed: 4 });
  state = playbackReducer(state, { type: 'seek', cursor: -5, head: 14 });
  expect(state).toMatchObject({ cursor: 1, playing: false });
  expect(playbackReducer(state, { type: 'tick' })).toBe(state);
  expect(playbackReducer(state, { type: 'follow' }).speed).toBe(4);
});

it('does not create a replay from missing data or accept invalid speeds', () => {
  expect(playbackReducer(initialPlayback, { type: 'toggle', head: 0 })).toBe(initialPlayback);
  expect(playbackReducer(initialPlayback, { type: 'speed', speed: 100 })).toBe(initialPlayback);
});
