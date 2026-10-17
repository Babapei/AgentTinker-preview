import { useEffect, useMemo, useReducer, type ReactNode } from 'react';
import { ChevronLeft, ChevronRight, FastForward, Pause, Play, SkipBack } from 'lucide-react';
import { projectEvents, terminal } from './event-log';
import { initialPlayback, playbackReducer } from './playback';
import type { RuntimeEvent, RunView } from './protocol';
import EventTimeline from './EventTimeline';
import Status from './Status';

export default function EventWorkspace({
  latest,
  events,
  available,
  selectSpan,
  children,
}: {
  latest: RunView;
  events: readonly RuntimeEvent[];
  available: boolean;
  selectSpan: (id: string) => void;
  children: (view: RunView) => ReactNode;
}) {
  const [playback, dispatch] = useReducer(playbackReducer, initialPlayback);
  const head = events.length;
  const position = playback.mode === 'follow' ? head : Math.min(playback.cursor, head);
  const boundary = playback.mode === 'follow' ? head : playback.boundary;
  const applied = useMemo(() => events.slice(0, position), [events, position]);
  const projected = useMemo(
    () => (playback.mode === 'history' ? projectEvents(applied) : null),
    [applied, playback.mode],
  );
  const view = projected ?? latest;
  useEffect(() => {
    if (!available && playback.playing) dispatch({ type: 'pause' });
  }, [available, playback.playing]);
  useEffect(() => {
    if (!playback.playing || !available) return;
    const timer = setTimeout(() => dispatch({ type: 'tick' }), 700 / playback.speed);
    return () => clearTimeout(timer);
  }, [playback.playing, playback.cursor, playback.speed, available]);
  const seek = (cursor: number) => dispatch({ type: 'seek', cursor, head });
  const ending = terminal(view.run.status)
    ? [...applied].reverse().find((event) => event.type === 'run.status_changed')
    : undefined;
  return (
    <div className="event-workspace">
      <section className="playback-panel" aria-label="历史记录播放">
        <div className="playback-heading">
          <div>
            <span className={`playback-mode ${playback.mode}`}>
              {playback.mode === 'history'
                ? playback.playing
                  ? '正在播放历史'
                  : '历史记录位置'
                : '最新记录'}
            </span>
            <span>
              {latest.run.mode === 'imported' ? '来源记录状态：' : '实际运行：'}
              <Status status={latest.run.status} />
            </span>
          </div>
          {playback.mode === 'history' && (
            <button className="text-button" onClick={() => dispatch({ type: 'follow' })}>
              <FastForward size={13} />
              返回最新{head > boundary && ` · ${head - boundary} 条新事件`}
            </button>
          )}
        </div>
        <div className="playback-controls">
          <button
            className="icon-button"
            aria-label="回到第一个事件"
            disabled={!available}
            onClick={() => seek(1)}
          >
            <SkipBack size={16} />
          </button>
          <button
            className="icon-button"
            aria-label="上一个事件"
            disabled={!available || position <= 1}
            onClick={() => dispatch({ type: 'step', delta: -1, head })}
          >
            <ChevronLeft size={17} />
          </button>
          <button
            className="play-button"
            disabled={!available}
            aria-label={playback.playing ? '暂停历史播放' : '播放历史记录'}
            onClick={() => dispatch({ type: 'toggle', head })}
          >
            {playback.playing ? <Pause size={14} /> : <Play size={14} />}
            {playback.playing ? '暂停播放' : '播放历史'}
          </button>
          <button
            className="icon-button"
            aria-label="下一个事件"
            disabled={!available || position >= boundary}
            onClick={() => dispatch({ type: 'step', delta: 1, head })}
          >
            <ChevronRight size={17} />
          </button>
          <input
            aria-label="历史事件位置"
            type="range"
            min={1}
            max={Math.max(1, boundary)}
            value={Math.max(1, position)}
            disabled={!available}
            onChange={(event) => seek(Number(event.target.value))}
          />
          <output aria-label="已应用事件位置">
            {available
              ? `${position} / ${boundary}`
              : !latest.run.capabilities.record_playback
                ? '仅摘要'
                : '待补齐'}
          </output>
          <select
            aria-label="历史播放速度"
            value={playback.speed}
            disabled={!available}
            onChange={(event) => dispatch({ type: 'speed', speed: Number(event.target.value) })}
          >
            {[0.5, 1, 2, 4].map((speed) => (
              <option value={speed} key={speed}>
                {speed}×
              </option>
            ))}
          </select>
        </div>
        <p>
          {playback.mode === 'history'
            ? '只重建已保存事件；播放或暂停均不改变实际任务。当前视图不含后续事件结果。'
            : '按事件逐步回看，不会重新运行模型或工具。'}
        </p>
      </section>
      {children(view)}
      {ending?.type === 'run.status_changed' && ending.data.reason !== null && (
        <p className="termination-note">
          已记录终止原因：<code>{ending.data.reason}</code>
        </p>
      )}
      {available && (
        <EventTimeline
          events={applied}
          head={boundary}
          choose={(event) => {
            seek(event.seq);
            if (event.span_id) selectSpan(event.span_id);
          }}
        />
      )}
    </div>
  );
}
