import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import payload from '../public/searchpo-content.json';

type Card = {
  label: string;
  value: string;
  detail: string;
};

type Payload = {
  title: string;
  summary: string;
  source: string;
  url: string;
  score: number | string | null;
  cards: Card[];
  footer: string;
};

const data = payload as Payload;

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

export const SearchpoRadar: React.FC = () => {
  const frame = useCurrentFrame();
  const sweep = interpolate(frame % 180, [0, 180], [-30, 130]);
  const titleEnter = spring({frame, fps: 30, config: {damping: 16, stiffness: 90}});
  const pulse = interpolate(Math.sin(frame / 12), [-1, 1], [0.2, 1]);

  return (
    <AbsoluteFill className="canvas">
      <div className="grid" />
      <div className="beam" style={{transform: `translateX(${sweep}%) rotate(-18deg)`}} />
      <div className="topbar">
        <span>searchpo radar</span>
        <span>daily candidate loop</span>
      </div>

      <section className="hero" style={{transform: `translateY(${interpolate(titleEnter, [0, 1], [56, 0])}px)`}}>
        <div className="kicker">Candidate Signal</div>
        <h1>{fitText(data.title, 72)}</h1>
        <p>{fitText(data.summary, 168)}</p>
      </section>

      <section className="score-row">
        <div className="score-ring" style={{boxShadow: `0 0 ${26 + pulse * 38}px rgba(32, 196, 133, 0.42)`}}>
          <span>{data.score ?? '-'}</span>
          <small>score</small>
        </div>
        <div className="source-box">
          <span>source</span>
          <strong>{fitText(data.source, 42)}</strong>
          <small>{fitText(data.url, 82)}</small>
        </div>
      </section>

      <section className="cards">
        {(data.cards || []).slice(0, 3).map((card, index) => (
          <CardBlock card={card} index={index} key={card.label} />
        ))}
      </section>

      <footer>{fitText(data.footer, 118)}</footer>
    </AbsoluteFill>
  );
};
