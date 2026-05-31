import {fitTextOnNLines} from '@remotion/layout-utils';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {FONT_FAMILY} from '../fonts';
import type {NormalizedStyle, Scene} from '../storyboard';
import type {Payload} from '../Composition';

type SceneBlockProps = {
  scene: Scene;
  data: Payload;
  index: number;
  count: number;
  style: NormalizedStyle;
  audioPulse: number;
};

const CARD_ACCENTS = ['#ffd60a', '#72e7ff', '#ff2d55'];

const text = (props: Record<string, unknown>, keys: string[], fallback = '', max = 120): string => {
  for (const key of keys) {
    const value = props[key];
    if (typeof value === 'string' && value.trim()) {
      const clean = value.replace(/\s+/g, ' ').trim();
      return clean.length > max ? `${clean.slice(0, max - 1).trim()}...` : clean;
    }
  }
  const clean = fallback.replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max - 1).trim()}...` : clean;
};

const list = (value: unknown, fallback: string[], max = 4): string[] => {
  const raw = Array.isArray(value) ? value : fallback;
  return raw
    .map((item) => text({item}, ['item'], '', 58))
    .filter(Boolean)
    .slice(0, max);
};

const fitLines = (value: string, maxLines: number, maxBoxWidth: number, maxFontSize: number) =>
  fitTextOnNLines({
    text: value,
    maxLines,
    maxBoxWidth,
    maxFontSize,
    fontFamily: FONT_FAMILY,
    fontWeight: 900,
    letterSpacing: '0px',
    validateFontIsLoaded: false,
  });

const useEnter = (delay = 0) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return spring({frame: frame - delay, fps, config: {damping: 18, stiffness: 110}});
};

const Kicker: React.FC<{children: string; tone?: 'cyan' | 'red'}> = ({children, tone}) => (
  <div className={`kicker${tone === 'cyan' ? ' kicker-cyan' : ''}${tone === 'red' ? ' kicker-red' : ''}`}>
    {children}
  </div>
);

const StatementScene: React.FC<SceneBlockProps> = ({scene, data}) => {
  const enter = useEnter(2);
  const title = text(scene.props, ['title'], data.displayTitle, 68);
  const sub = text(scene.props, ['sub', 'subtitle', 'detail'], data.summary, 110);
  const titleFit = fitLines(title, 3, 900, 96);
  return (
    <AbsoluteFill className="scene scene-hook scene-statement" style={{opacity: enter}}>
      <Kicker>{text(scene.props, ['kicker'], '今天为什么刷到它', 18)}</Kicker>
      <h1 style={{fontSize: titleFit.fontSize, transform: `translateY(${interpolate(enter, [0, 1], [48, 0])}px)`}}>
        {titleFit.lines.map((line, index) => (
          <span className="fit-line" key={`${line}-${index}`}>
            {line}
          </span>
        ))}
      </h1>
      <p className="hook-sub">{sub}</p>
    </AbsoluteFill>
  );
};

const ContextScene: React.FC<SceneBlockProps> = ({scene, data, audioPulse}) => {
  const enter = useEnter(2);
  const overview = text(scene.props, ['text', 'summary', 'detail'], data.summary, 128);
  const fit = fitLines(overview, 4, 900, 56);
  return (
    <AbsoluteFill className="scene scene-overview scene-context" style={{opacity: enter}}>
      <Kicker tone="cyan">{text(scene.props, ['kicker'], '一句话看懂', 18)}</Kicker>
      <p className="overview-text" style={{fontSize: fit.fontSize, transform: `translateY(${interpolate(enter, [0, 1], [36, 0])}px)`}}>
        {fit.lines.map((line, index) => (
          <span className="fit-line" key={`${line}-${index}`}>
            {line}
          </span>
        ))}
      </p>
      <div className="signal-row">
        <div
          className="signal-pill"
          style={{boxShadow: `0 0 ${18 + audioPulse * 34}px rgba(255, 214, 10, 0.28)`}}
        >
          <span>{text(scene.props, ['metric', 'value'], data.audienceMetricLine, 28)}</span>
          <small>{text(scene.props, ['metricNote', 'note'], data.evidenceLevel.includes('unverified') ? '证据边界' : '实时信号', 18)}</small>
        </div>
        <div className="source-line">
          <span>{text(scene.props, ['sourceLabel'], '来源边界', 18)}</span>
          <strong>{text(scene.props, ['sourceValue', 'source'], data.source ? `${data.source} 已留档` : '来源已留档', 76)}</strong>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const StatScene: React.FC<SceneBlockProps> = ({scene, data, audioPulse}) => {
  const enter = useEnter(2);
  const value = text(scene.props, ['value', 'stat'], data.audienceMetricLine, 30);
  const label = text(scene.props, ['label', 'heading'], data.displayTitle, 54);
  const detail = text(scene.props, ['detail', 'sub'], data.summary, 104);
  return (
    <AbsoluteFill className="scene scene-stat" style={{opacity: enter}}>
      <Kicker>{text(scene.props, ['kicker'], '一个信号', 18)}</Kicker>
      <div className="stat-value" style={{transform: `scale(${0.96 + audioPulse * 0.04})`}}>
        {value}
      </div>
      <div className="stat-label">{label}</div>
      <p className="stat-detail">{detail}</p>
    </AbsoluteFill>
  );
};

const BulletsScene: React.FC<SceneBlockProps> = ({scene, data}) => {
  const enter = useEnter(2);
  const items = list(scene.props.items, data.cards.map((card) => card.value), 4);
  return (
    <AbsoluteFill className="scene scene-bullets" style={{opacity: enter}}>
      <Kicker tone="cyan">{text(scene.props, ['kicker'], '拆成几步看', 18)}</Kicker>
      <h2>{text(scene.props, ['heading', 'title'], data.displayTitle, 56)}</h2>
      <div className="bullet-list">
        {items.map((item, index) => (
          <div className="bullet-row" key={`${item}-${index}`} style={{transform: `translateX(${interpolate(enter, [0, 1], [36 - index * 6, 0])}px)`}}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <strong>{item}</strong>
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
};

const CardScene: React.FC<SceneBlockProps> = ({scene, data, index}) => {
  const enter = useEnter(2);
  const accent = CARD_ACCENTS[index % CARD_ACCENTS.length];
  const label = text(scene.props, ['label'], data.cards[index]?.label || '证据', 18);
  const value = text(scene.props, ['value'], data.cards[index]?.value || data.displayTitle, 48);
  const detail = text(scene.props, ['detail'], data.cards[index]?.detail || data.summary, 120);
  return (
    <AbsoluteFill className="scene scene-card" style={{opacity: enter}}>
      <div className="card-index" style={{color: accent}}>
        {String(index + 1).padStart(2, '0')}
      </div>
      <div className="big-card" style={{borderLeftColor: accent, transform: `translateX(${interpolate(enter, [0, 1], [40, 0])}px)`}}>
        <div className="big-card-label" style={{color: accent}}>{label}</div>
        <div className="big-card-value">{value}</div>
        <div className="big-card-detail">{detail}</div>
      </div>
    </AbsoluteFill>
  );
};

const CompareScene: React.FC<SceneBlockProps> = ({scene, data}) => {
  const enter = useEnter(2);
  return (
    <AbsoluteFill className="scene scene-compare" style={{opacity: enter}}>
      <Kicker>{text(scene.props, ['kicker'], '别混在一起', 18)}</Kicker>
      <h2>{text(scene.props, ['heading', 'title'], data.displayTitle, 56)}</h2>
      <div className="compare-grid">
        <div>
          <span>{text(scene.props, ['leftLabel'], '已知', 14)}</span>
          <strong>{text(scene.props, ['left'], data.cards[0]?.detail || data.summary, 90)}</strong>
        </div>
        <div>
          <span>{text(scene.props, ['rightLabel'], '待证', 14)}</span>
          <strong>{text(scene.props, ['right'], data.verificationNextStep, 90)}</strong>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const QuoteScene: React.FC<SceneBlockProps> = ({scene, data}) => {
  const enter = useEnter(2);
  const quote = text(scene.props, ['quote', 'text'], data.summary, 112);
  const fit = fitLines(quote, 4, 860, 62);
  return (
    <AbsoluteFill className="scene scene-quote" style={{opacity: enter}}>
      <Kicker tone="cyan">{text(scene.props, ['kicker'], '原始信号', 18)}</Kicker>
      <div className="quote-mark">“</div>
      <p style={{fontSize: fit.fontSize}}>
        {fit.lines.map((line, index) => (
          <span className="fit-line" key={`${line}-${index}`}>
            {line}
          </span>
        ))}
      </p>
      <small>{text(scene.props, ['attribution', 'source'], data.source || '来源已留档', 42)}</small>
    </AbsoluteFill>
  );
};

const CtaScene: React.FC<SceneBlockProps> = ({scene, data}) => {
  const enter = useEnter(2);
  return (
    <AbsoluteFill className="scene scene-cta" style={{opacity: enter}}>
      <Kicker tone="red">{text(scene.props, ['kicker'], '先别急着下结论', 18)}</Kicker>
      <div className="cta-text" style={{transform: `scale(${interpolate(enter, [0, 1], [0.92, 1])})`}}>
        {text(scene.props, ['text'], data.cta, 48)}
      </div>
      <div className="cta-footer">{text(scene.props, ['footer'], data.verificationNextStep || data.footer, 80)}</div>
    </AbsoluteFill>
  );
};

export const SceneBlock: React.FC<SceneBlockProps> = (props) => {
  switch (props.scene.type) {
    case 'statement':
      return <StatementScene {...props} />;
    case 'context':
      return <ContextScene {...props} />;
    case 'stat':
      return <StatScene {...props} />;
    case 'bullets':
      return <BulletsScene {...props} />;
    case 'compare':
      return <CompareScene {...props} />;
    case 'quote':
      return <QuoteScene {...props} />;
    case 'cta':
      return <CtaScene {...props} />;
    case 'card':
    default:
      return <CardScene {...props} />;
  }
};
