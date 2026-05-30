import {AbsoluteFill, Audio, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import payload from '../public/searchpo-content.json';
import {Captions} from './Captions';

type Card = {
  label: string;
  value: string;
  detail: string;
};

export type Payload = {
  badge?: string;
  title: string;
  summary: string;
  source: string;
  url: string;
  score: number | string | null;
  metricLine?: string;
  cards: Card[];
  audioSrc?: string | null;
  voiceoverText?: string | null;
  cta?: string;
  footer: string;
};

const samplePayload = payload as Payload;

const payloadFor = (props: Partial<Payload>): Payload => ({
  ...samplePayload,
  ...props,
  cards: props.cards && props.cards.length > 0 ? props.cards : samplePayload.cards,
});

const fitText = (text: string, max = 96) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

const CardBlock: React.FC<{card: Card; index: number}> = ({card, index}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = spring({
    frame: frame - 58 - index * 24,
    fps,
    config: {damping: 18, stiffness: 110},
  });

  return (
    <div
      className="card"
      style={{
        opacity: interpolate(enter, [0, 1], [0, 1]),
        transform: `translateY(${interpolate(enter, [0, 1], [44, 0])}px)`,
      }}
    >
      <div className="card-label">{card.label}</div>
      <div className="card-value">{fitText(card.value, 54)}</div>
      <div className="card-detail">{fitText(card.detail, 118)}</div>
    </div>
  );
};

export const SearchpoRadar: React.FC<Partial<Payload>> = (props) => {
  const data = payloadFor(props);
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const sweep = interpolate(frame % 150, [0, 150], [-45, 125]);
  const titleEnter = spring({frame: frame - 8, fps: 30, config: {damping: 16, stiffness: 90}});
  const cardEnter = spring({frame: frame - 42, fps: 30, config: {damping: 20, stiffness: 95}});
  const pulse = interpolate(Math.sin(frame / 10), [-1, 1], [0.45, 1]);

  const introOpacity = interpolate(frame, [0, 18], [0, 1], {extrapolateRight: 'clamp'});
  const outroOpacity = interpolate(frame, [durationInFrames - 30, durationInFrames - 6], [1, 0], {extrapolateLeft: 'clamp'});
  const masterOpacity = Math.min(introOpacity, outroOpacity);

  return (
    <AbsoluteFill className="canvas" style={{opacity: masterOpacity}}>
      {data.audioSrc ? <Audio src={staticFile(data.audioSrc)} /> : null}
      <div className="noise" />
      <div className="beam" style={{transform: `translateX(${sweep}%) rotate(-14deg)`}} />
      <div className="topbar">
        <span>{data.badge || '今日 AI 工具热点'}</span>
        <span>#{fitText(data.source, 18)}</span>
      </div>

      <section className="hero" style={{transform: `translateY(${interpolate(titleEnter, [0, 1], [56, 0])}px)`}}>
        <div className="kicker">今天为什么刷到它</div>
        <h1>{fitText(data.title, 72)}</h1>
        <p>{fitText(data.voiceoverText || data.summary, 112)}</p>
      </section>

      <section className="signal-row">
        <div className="signal-pill" style={{boxShadow: `0 0 ${18 + pulse * 28}px rgba(255, 214, 10, 0.28)`}}>
          <span>{fitText(data.metricLine || `score ${data.score ?? '-'}`, 28)}</span>
          <small>实时信号</small>
        </div>
        <div className="source-line">
          <span>来源边界</span>
          <strong>{fitText(data.url, 66)}</strong>
        </div>
      </section>

      <section className="cards" style={{opacity: interpolate(cardEnter, [0, 1], [0, 1])}}>
        {(data.cards || []).slice(0, 3).map((card, index) => (
          <CardBlock card={card} index={index} key={card.label} />
        ))}
      </section>

      {data.voiceoverText ? (
        <Captions text={data.voiceoverText} startFrame={20} />
      ) : null}

      <footer>
        <span>{fitText(data.cta || '先放进候选池，别把热度当结论。', 42)}</span>
        <small>{fitText(data.footer, 48)}</small>
      </footer>
    </AbsoluteFill>
  );
};
