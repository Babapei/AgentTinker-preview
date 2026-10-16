export type Playback = {
  mode: 'follow' | 'history';
  cursor: number;
  boundary: number;
  playing: boolean;
  speed: number;
};
export type PlaybackAction =
  | { type: 'seek'; cursor: number; head: number }
  | { type: 'step'; delta: -1 | 1; head: number }
  | { type: 'toggle'; head: number }
  | { type: 'tick' }
  | { type: 'pause' }
  | { type: 'speed'; speed: number }
  | { type: 'follow' };

export const initialPlayback: Playback = {
  mode: 'follow',
  cursor: 1,
  boundary: 0,
  playing: false,
  speed: 1,
};

export function playbackReducer(state: Playback, action: PlaybackAction): Playback {
  switch (action.type) {
    case 'follow':
      return { ...initialPlayback, speed: state.speed };
    case 'pause':
      return { ...state, playing: false };
    case 'speed':
      return [0.5, 1, 2, 4].includes(action.speed) ? { ...state, speed: action.speed } : state;
    case 'tick': {
      if (!state.playing || state.mode !== 'history') return state;
      const cursor = Math.min(state.cursor + 1, state.boundary);
      return { ...state, cursor, playing: cursor < state.boundary };
    }
    case 'toggle': {
      if (state.playing) return { ...state, playing: false };
      if (action.head < 1) return state;
      const boundary = state.mode === 'follow' ? action.head : state.boundary;
      return {
        ...state,
        mode: 'history',
        boundary,
        playing: boundary > 1,
        cursor: state.mode === 'follow' || state.cursor >= boundary ? 1 : state.cursor,
      };
    }
    case 'step':
    case 'seek': {
      if (action.head < 1) return state;
      const boundary = state.mode === 'follow' ? action.head : state.boundary;
      const position =
        action.type === 'step'
          ? (state.mode === 'follow' ? action.head : state.cursor) + action.delta
          : action.cursor;
      return {
        ...state,
        mode: 'history',
        playing: false,
        boundary,
        cursor: Math.max(1, Math.min(boundary, position)),
      };
    }
  }
}
