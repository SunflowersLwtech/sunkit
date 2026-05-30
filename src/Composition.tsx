import {
  AbsoluteFill,
  Audio,
  interpolate,
  Series,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {Captions, type CaptionSegment} from './Captions';

type Card = {
  label: string;
  value: string;
  detail: string;
};

export type Payload = {
  badge: string;
  title: string;
  summary: string;
  source: string;
  url: string;
  score: number | string | null;
  metricLine: string;
  cards: Card[];
  audioSrc: string;
  voiceoverText: string;
  captions: CaptionSegment[];
  durationInFrames: number;
  fps: number;
  cta: string;
  footer: string;
};

const fitText = (text: string, max = 96) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

const CARD_ACCENTS = ['#ffd60a', '#72e7ff', '#ff2d55'];

const requireText = (value: string | null | undefined, field: string): string => {
  if (!value || !value.trim()) {
    throw new Error(`SearchpoRadar missing required prop: ${field}`);
  }
  return value;
};

const requireCards = (cards: Card[] | null | undefined): Card[] => {
  if (!Array.isArray(cards) || cards.length === 0) {
    throw new Error('SearchpoRadar requires at least one card from DeepSeek polish output.');
  }
  return cards;
};

const requireCaptions = (captions: CaptionSegment[] | null | undefined): CaptionSegment[] => {
  if (!Array.isArray(captions) || captions.length === 0) {
    throw new Error('SearchpoRadar requires timed captions from scripts/build_captions.py.');
  }
  return captions;
};

export const assertPayload = (props: Partial<Payload>): Payload => {
  const durationInFrames = props.durationInFrames;
  const fps = props.fps;
  if (!Number.isFinite(durationInFrames) || !durationInFrames || durationInFrames < 60) {
    throw new Error('SearchpoRadar requires props.durationInFrames >= 60.');
  }
  if (!Number.isFinite(fps) || !fps || fps < 1) {
    throw new Error('SearchpoRadar requires props.fps.');
  }
  return {
    badge: requireText(props.badge, 'badge'),
    title: requireText(props.title, 'title'),
    summary: requireText(props.summary, 'summary'),
    source: requireText(props.source, 'source'),
    url: requireText(props.url, 'url'),
    score: props.score ?? null,
    metricLine: requireText(props.metricLine, 'metricLine'),
    cards: requireCards(props.cards),
    audioSrc: requireText(props.audioSrc, 'audioSrc'),
    voiceoverText: requireText(props.voiceoverText, 'voiceoverText'),
    captions: requireCaptions(props.captions),
    durationInFrames: Math.round(durationInFrames),
    fps: Math.round(fps),
    cta: requireText(props.cta, 'cta'),
    footer: requireText(props.footer, 'footer'),
  };
};

// Allocate integer scene durations that sum exactly to the total, distributing
// the rounding remainder to the largest fractional parts.
const computeSceneFrames = (total: number, weights: number[]): number[] => {
  const wsum = weights.reduce((a, b) => a + b, 0);
  if (wsum <= 0) {
    throw new Error('SearchpoRadar scene weights must sum to a positive value.');
  }
  const raw = weights.map((w) => (w / wsum) * total);
  const floored = raw.map(Math.floor);
  let remainder = total - floored.reduce((a, b) => a + b, 0);
  const order = raw
    .map((r, i) => ({i, frac: r - Math.floor(r)}))
    .sort((a, b) => b.frac - a.frac);
  for (let k = 0; remainder > 0 && order.length > 0; k++, remainder--) {
    floored[order[k % order.length].i] += 1;
  }
  return floored.map((f) => Math.max(1, f));
};

// Spring entrance helper, relative to the current (Series) sequence frame.
const useEnter = (delay = 0) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - delay, fps, config: {damping: 18, stiffness: 110}});
};

const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const sweep = interpolate(frame % 150, [0, 150], [-45, 125]);
  return (
    <>
      <div className="noise" />
      <div className="beam" style={{transform: `translateX(${sweep}%) rotate(-14deg)`}} />
    </>
  );
};

const TopBar: React.FC<{data: Payload}> = ({data}) => (
  <div className="topbar">
    <span>{requireText(data.badge, 'badge')}</span>
    <span className="topbar-source">{fitText(data.source, 18)}</span>
  </div>
);

// Segmented progress indicator showing which scene is playing.
const SceneProgress: React.FC<{boundaries: number[]; total: number}> = ({boundaries, total}) => {
  const frame = useCurrentFrame();
  return (
    <div className="progress-row">
      {boundaries.map((start, i) => {
        const end = i + 1 < boundaries.length ? boundaries[i + 1] : total;
        const local = interpolate(frame, [start, end], [0, 1], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
        return (
          <div className="progress-seg" key={i}>
            <div className="progress-fill" style={{width: `${local * 100}%`}} />
          </div>
        );
      })}
    </div>
  );
};

const HookScene: React.FC<{data: Payload}> = ({data}) => {
  const enter = useEnter(2);
  return (
    <AbsoluteFill className="scene scene-hook" style={{opacity: enter}}>
      <div className="kicker">今天为什么刷到它</div>
      <h1 style={{transform: `translateY(${interpolate(enter, [0, 1], [48, 0])}px)`}}>
        {fitText(data.title, 60)}
      </h1>
      <p className="hook-sub">{fitText(requireText(data.voiceoverText, 'voiceoverText'), 80)}</p>
    </AbsoluteFill>
  );
};

const OverviewScene: React.FC<{data: Payload}> = ({data}) => {
  const enter = useEnter(2);
  const frame = useCurrentFrame();
  const pulse = interpolate(Math.sin(frame / 9), [-1, 1], [0.45, 1]);
  return (
    <AbsoluteFill className="scene scene-overview" style={{opacity: enter}}>
      <div className="kicker kicker-cyan">一句话看懂</div>
      <p className="overview-text" style={{transform: `translateY(${interpolate(enter, [0, 1], [36, 0])}px)`}}>
        {fitText(data.summary, 110)}
      </p>
      <div className="signal-row">
        <div
          className="signal-pill"
          style={{boxShadow: `0 0 ${18 + pulse * 28}px rgba(255, 214, 10, 0.28)`}}
        >
          <span>{fitText(requireText(data.metricLine, 'metricLine'), 26)}</span>
          <small>实时信号</small>
        </div>
        <div className="source-line">
          <span>来源边界</span>
          <strong>{fitText(data.url, 64)}</strong>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const CardScene: React.FC<{card: Card; index: number; count: number}> = ({card, index, count}) => {
  const enter = useEnter(2);
  const accent = CARD_ACCENTS[index % CARD_ACCENTS.length];
  return (
    <AbsoluteFill className="scene scene-card" style={{opacity: enter}}>
      <div className="card-index" style={{color: accent}}>
        {String(index + 1).padStart(2, '0')} / {String(count).padStart(2, '0')}
      </div>
      <div className="big-card" style={{borderLeftColor: accent, transform: `translateX(${interpolate(enter, [0, 1], [40, 0])}px)`}}>
        <div className="big-card-label" style={{color: accent}}>{fitText(card.label, 18)}</div>
        <div className="big-card-value">{fitText(card.value, 40)}</div>
        <div className="big-card-detail">{fitText(card.detail, 110)}</div>
      </div>
    </AbsoluteFill>
  );
};

const CtaScene: React.FC<{data: Payload}> = ({data}) => {
  const enter = useEnter(2);
  return (
    <AbsoluteFill className="scene scene-cta" style={{opacity: enter}}>
      <div className="kicker kicker-red">先别急着下结论</div>
      <div className="cta-text" style={{transform: `scale(${interpolate(enter, [0, 1], [0.92, 1])})`}}>
        {fitText(requireText(data.cta, 'cta'), 42)}
      </div>
      <div className="cta-footer">{fitText(data.footer, 56)}</div>
    </AbsoluteFill>
  );
};

export const SearchpoRadar: React.FC<Partial<Payload>> = (props) => {
  const data = assertPayload(props);
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();

  const captions = data.captions;
  const cards = data.cards.slice(0, 3);
  // hook, overview, one weight per card, cta
  const weights = [0.2, 0.18, ...cards.map(() => 0.15), 0.17];
  const sceneFrames = computeSceneFrames(durationInFrames, weights);
  const boundaries: number[] = [];
  sceneFrames.reduce((acc, f) => {
    boundaries.push(acc);
    return acc + f;
  }, 0);

  const introOpacity = interpolate(frame, [0, 14], [0, 1], {extrapolateRight: 'clamp'});
  const outroOpacity = interpolate(
    frame,
    [durationInFrames - 24, durationInFrames - 6],
    [1, 0],
    {extrapolateLeft: 'clamp'},
  );
  const masterOpacity = Math.min(introOpacity, outroOpacity);

  return (
    <AbsoluteFill className="canvas" style={{opacity: masterOpacity}}>
      <Audio src={staticFile(data.audioSrc)} />
      <Background />
      <TopBar data={data} />
      <SceneProgress boundaries={boundaries} total={durationInFrames} />

      <Series>
        <Series.Sequence durationInFrames={sceneFrames[0]}>
          <HookScene data={data} />
        </Series.Sequence>
        <Series.Sequence durationInFrames={sceneFrames[1]}>
          <OverviewScene data={data} />
        </Series.Sequence>
        {cards.map((card, index) => (
          <Series.Sequence durationInFrames={sceneFrames[2 + index]} key={card.label || index}>
            <CardScene card={card} index={index} count={cards.length} />
          </Series.Sequence>
        ))}
        <Series.Sequence durationInFrames={sceneFrames[sceneFrames.length - 1]}>
          <CtaScene data={data} />
        </Series.Sequence>
      </Series>

      <Captions segments={captions} />
    </AbsoluteFill>
  );
};
