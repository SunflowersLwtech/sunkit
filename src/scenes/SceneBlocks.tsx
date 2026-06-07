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

const optionalText = (props: Record<string, unknown>, keys: string[], fallback = '', max = 120): string => {
  for (const key of keys) {
    if (!Object.prototype.hasOwnProperty.call(props, key)) {
      continue;
    }
    const value = props[key];
    if (typeof value !== 'string') {
      continue;
    }
    const clean = value.replace(/\s+/g, ' ').trim();
    return clean.length > max ? `${clean.slice(0, max - 1).trim()}...` : clean;
  }
  return text({}, [], fallback, max);
};

const list = (value: unknown, fallback: string[], max = 4): string[] => {
  const raw = Array.isArray(value) ? value : fallback;
  return raw
    .map((item) => text({item}, ['item'], '', 58))
    .filter(Boolean)
    .slice(0, max);
};

const numericSeries = (value: unknown, fallback: number[]): number[] => {
  const raw = Array.isArray(value) ? value : fallback;
  const values = raw
    .map((item) => {
      const match = String(item).replace(/,/g, '').match(/-?\d+(?:\.\d+)?/);
      return match ? Number(match[0]) : Number.NaN;
    })
    .filter((item) => Number.isFinite(item));
  return (values.length >= 2 ? values : fallback).slice(0, 5);
};

const splitRow = (row: string, fallbackIndex: number): [string, string, string] => {
  const parts = row.split('|').map((part) => part.trim()).filter(Boolean);
  if (parts.length >= 3) {
    return [parts[0], parts[1], parts.slice(2).join(' / ')];
  }
  if (parts.length === 2) {
    return [`维度 ${fallbackIndex + 1}`, parts[0], parts[1]];
  }
  return [`维度 ${fallbackIndex + 1}`, row, '判断边界'];
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
  const sub = optionalText(scene.props, ['sub', 'subtitle', 'detail'], data.summary, 110);
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
  const detail = optionalText(scene.props, ['detail', 'sub'], data.summary, 104);
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
  const detail = optionalText(scene.props, ['detail'], data.cards[index]?.detail || data.summary, 120);
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

const CompareTableScene: React.FC<SceneBlockProps> = ({scene, data}) => {
  const enter = useEnter(2);
  const rows = list(
    scene.props.rows || scene.props.items,
    data.cards.slice(0, 4).map((card) => `${card.label}|${card.value}|${card.detail}`),
    4,
  );
  return (
    <AbsoluteFill className="scene scene-compare-table" style={{opacity: enter}}>
      <Kicker>{text(scene.props, ['kicker'], '横向比较', 18)}</Kicker>
      <h2>{text(scene.props, ['heading', 'title'], data.displayTitle, 56)}</h2>
      <div className="compare-table">
        <div className="compare-table-head">
          <span>维度</span>
          <span>{text(scene.props, ['leftLabel'], '当前方案', 14)}</span>
          <span>{text(scene.props, ['rightLabel'], '失败边界', 14)}</span>
        </div>
        {rows.map((row, index) => {
          const [label, left, right] = splitRow(row, index);
          return (
            <div
              className="compare-table-row"
              key={`${label}-${index}`}
              style={{transform: `translateY(${interpolate(enter, [0, 1], [18 - index * 3, 0])}px)`}}
            >
              <span>{label}</span>
              <strong>{left}</strong>
              <em>{right}</em>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const TerminalScene: React.FC<SceneBlockProps> = ({scene, data, audioPulse}) => {
  const enter = useEnter(2);
  const frame = useCurrentFrame();
  const prompt = text(scene.props, ['prompt'], '$', 8);
  const lines = list(scene.props.lines || scene.props.commands || scene.props.items, [
    'clone / install',
    'run quick start',
    'inspect examples',
    'check tests',
  ], 5);
  return (
    <AbsoluteFill className="scene scene-terminal" style={{opacity: enter}}>
      <Kicker tone="cyan">{text(scene.props, ['kicker'], '把它放进终端看', 18)}</Kicker>
      <div className="terminal-window" style={{boxShadow: `0 0 ${24 + audioPulse * 36}px rgba(114, 231, 255, 0.16)`}}>
        <div className="terminal-bar">
          <div className="terminal-lights"><span /><span /><span /></div>
          <strong>{text(scene.props, ['title', 'heading'], data.displayTitle, 42)}</strong>
        </div>
        <div className="terminal-body">
          {lines.map((line, index) => {
            const delay = index * 16;
            const reveal = Math.max(0, Math.min(Array.from(line).length, Math.floor((frame - delay) / 1.5)));
            const rendered = Array.from(line).slice(0, reveal).join('');
            return (
              <div className="terminal-line" key={`${line}-${index}`}>
                <span>{prompt}</span>
                <code>{rendered || ' '}</code>
              </div>
            );
          })}
          <div className="terminal-status">evidence boundary: source-backed, not hype</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const FlowScene: React.FC<SceneBlockProps> = ({scene, data, audioPulse}) => {
  const enter = useEnter(2);
  const nodes = list(scene.props.nodes || scene.props.steps || scene.props.items, ['输入', '核心模块', '输出', '失败边界'], 5);
  return (
    <AbsoluteFill className="scene scene-flow" style={{opacity: enter}}>
      <Kicker tone="cyan">{text(scene.props, ['kicker'], '机制怎么跑', 18)}</Kicker>
      <h2>{text(scene.props, ['heading', 'title'], data.displayTitle, 56)}</h2>
      <div className="flow-diagram" style={{boxShadow: `0 0 ${28 + audioPulse * 32}px rgba(114, 231, 255, 0.14)`}}>
        {nodes.map((node, index) => (
          <div className="flow-step" key={`${node}-${index}`}>
            <div
              className="flow-node"
              style={{
                opacity: interpolate(enter, [0, 1], [0.35 + index * 0.08, 1]),
                transform: `translateY(${interpolate(enter, [0, 1], [28 - index * 4, 0])}px)`,
              }}
            >
              <span>{String(index + 1).padStart(2, '0')}</span>
              <strong>{node}</strong>
            </div>
            {index < nodes.length - 1 ? <div className="flow-arrow">→</div> : null}
          </div>
        ))}
      </div>
      <p className="flow-caption">{text(scene.props, ['caption', 'detail', 'summary'], '把机制画出来，才不是把文字贴到屏幕上。', 80)}</p>
    </AbsoluteFill>
  );
};

const ChartScene: React.FC<SceneBlockProps> = ({scene, data, audioPulse}) => {
  const enter = useEnter(2);
  const series = numericSeries(scene.props.points || scene.props.items, [18, 36, 52, 71, 88]);
  const max = Math.max(...series, 1);
  const min = Math.min(...series, 0);
  const range = Math.max(1, max - min);
  const progress = Math.max(0, Math.min(1, interpolate(enter, [0, 1], [0.05, 1])));
  const points = series.map((value, index) => {
    const x = 80 + (index / Math.max(1, series.length - 1)) * 760;
    const y = 300 - ((value - min) / range) * 220;
    return {x, y, value};
  });
  const polyline = points.map((point) => `${point.x},${point.y}`).join(' ');
  return (
    <AbsoluteFill className="scene scene-chart" style={{opacity: enter}}>
      <Kicker>{text(scene.props, ['kicker'], '一个数据点', 18)}</Kicker>
      <div className="chart-shell">
        <div className="chart-copy">
          <h2>{text(scene.props, ['heading', 'title'], data.displayTitle, 56)}</h2>
          <div className="chart-value">{text(scene.props, ['value', 'stat'], data.audienceMetricLine, 28)}</div>
          <p>{text(scene.props, ['label'], '热度只当信号，结论要看判断框架。', 48)}</p>
        </div>
        <svg className="chart-svg" viewBox="0 0 920 340" role="img">
          {[0, 1, 2, 3].map((line) => (
            <line className="chart-grid-line" key={line} x1="64" x2="860" y1={70 + line * 70} y2={70 + line * 70} />
          ))}
          <polyline
            className="chart-line"
            points={polyline}
            style={{strokeDasharray: 1100, strokeDashoffset: 1100 * (1 - progress)}}
          />
          {points.map((point, index) => (
            <g key={`${point.x}-${index}`} style={{opacity: index / Math.max(1, points.length - 1) <= progress ? 1 : 0}}>
              <circle className="chart-dot" cx={point.x} cy={point.y} r={10 + audioPulse * 3} />
              <text x={point.x} y={point.y - 18}>{String(point.value)}</text>
            </g>
          ))}
        </svg>
      </div>
    </AbsoluteFill>
  );
};

const CodeDiffScene: React.FC<SceneBlockProps> = ({scene, data}) => {
  const enter = useEnter(2);
  const additions = list(scene.props.additions || scene.props.added || scene.props.items, [
    '看入口模块',
    '看示例输入输出',
    '看测试和 CI',
  ], 4);
  const removals = list(scene.props.removals || scene.props.removed, ['只看 star 数'], 2);
  const rows = [
    ...removals.map((line) => ({kind: 'remove', line})),
    ...additions.map((line) => ({kind: 'add', line})),
  ];
  return (
    <AbsoluteFill className="scene scene-code-diff" style={{opacity: enter}}>
      <Kicker tone="cyan">{text(scene.props, ['kicker'], '代码视角', 18)}</Kicker>
      <div className="diff-layout">
        <div className="diff-copy">
          <h2>{text(scene.props, ['title', 'heading'], data.displayTitle, 50)}</h2>
          <p>{text(scene.props, ['summary', 'detail'], '高质量解说要把 repo 从代码堆还原成设计系统。', 70)}</p>
        </div>
        <div className="diff-window">
          <div className="diff-file">{text(scene.props, ['filename', 'file'], 'repo / docs / tests', 34)}</div>
          {rows.map((row, index) => (
            <div className={`diff-row diff-${row.kind}`} key={`${row.kind}-${row.line}-${index}`} style={{opacity: interpolate(enter, [0, 1], [0.35 + index * 0.08, 1])}}>
              <span>{row.kind === 'add' ? '+' : '-'}</span>
              <code>{row.line}</code>
            </div>
          ))}
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
      <Kicker tone="red">{text(scene.props, ['kicker'], '判断框架', 18)}</Kicker>
      <div className="cta-text" style={{transform: `scale(${interpolate(enter, [0, 1], [0.92, 1])})`}}>
        {text(scene.props, ['text'], data.cta, 48)}
      </div>
      <div className="cta-footer">{optionalText(scene.props, ['footer'], data.verificationNextStep || data.footer, 80)}</div>
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
    case 'compare_table':
      return <CompareTableScene {...props} />;
    case 'terminal':
      return <TerminalScene {...props} />;
    case 'flow':
      return <FlowScene {...props} />;
    case 'chart':
      return <ChartScene {...props} />;
    case 'code_diff':
      return <CodeDiffScene {...props} />;
    case 'quote':
      return <QuoteScene {...props} />;
    case 'cta':
      return <CtaScene {...props} />;
    case 'card':
    default:
      return <CardScene {...props} />;
  }
};
