import React from 'react';
import {fitTextOnNLines} from '@remotion/layout-utils';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {seededRandom, useContinuousPulse, useFloat} from '../utils/kinetics';
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

const list = (value: unknown, fallback: string[], max = 4, itemMax = 58): string[] => {
  const raw = Array.isArray(value) ? value : fallback;
  const items = raw
    .map((item) => text({item}, ['item'], '', itemMax))
    .filter(Boolean)
    .slice(0, max);
  return items.length > 0 ? items : fallback.slice(0, max);
};

const codeLines = (value: unknown, fallback: string[], max = 14): string[] => {
  const raw = Array.isArray(value) ? value : fallback;
  const items = raw
    .map((item) => {
      const clean = String(item ?? '').replace(/\s+$/g, '');
      return clean.length > 88 ? `${clean.slice(0, 87).trimEnd()}...` : clean;
    })
    .filter((item) => item.trim())
    .slice(0, max);
  return items.length > 0 ? items : fallback.slice(0, max);
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
  return [`维度 ${fallbackIndex + 1}`, row, '待验证'];
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
  return spring({frame: frame - delay, fps, config: {damping: 12, stiffness: 100}});
};

const Kicker: React.FC<{children: string; tone?: 'cyan' | 'red'}> = ({children, tone}) => (
  <div className={`kicker${tone === 'cyan' ? ' kicker-cyan' : ''}${tone === 'red' ? ' kicker-red' : ''}`}>
    {children}
  </div>
);

const StatementScene: React.FC<SceneBlockProps> = ({scene, data}) => {
  const enter = useEnter(2);
  const floatY = useFloat(0.03, 6);
  const title = text(scene.props, ['title'], data.displayTitle, 68);
  const sub = optionalText(scene.props, ['sub', 'subtitle', 'detail'], data.summary, 110);
  const titleFit = fitLines(title, 3, 900, 96);

  // Create deterministic background dots
  const dots = React.useMemo(() => Array.from({length: 12}).map((_, i) => ({
    x: seededRandom(i) * 1920,
    y: seededRandom(i + 100) * 1080,
    size: 2 + seededRandom(i + 200) * 4,
  })), []);

  return (
    <AbsoluteFill className="scene scene-hook scene-statement" style={{opacity: enter}}>
      {dots.map((dot, i) => (
        <div key={i} style={{position: 'absolute', left: dot.x, top: dot.y, width: dot.size, height: dot.size, borderRadius: '50%', background: 'rgba(255,255,255,0.05)'}} />
      ))}
      <Kicker>{text(scene.props, ['kicker'], '今天为什么刷到它', 18)}</Kicker>
      <h1 style={{fontSize: titleFit.fontSize, transform: `translateY(${interpolate(enter, [0, 1], [48, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}) + floatY}px)`}}>
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
  const pulse = useContinuousPulse(0.04, 0.4, 1.0);
  const overview = text(scene.props, ['text', 'summary', 'detail'], data.summary, 128);
  const fit = fitLines(overview, 4, 900, 56);
  return (
    <AbsoluteFill className="scene scene-overview scene-context" style={{opacity: enter}}>
      <Kicker tone="cyan">{text(scene.props, ['kicker'], '一句话看懂', 18)}</Kicker>
      <p className="overview-text" style={{fontSize: fit.fontSize, transform: `translateY(${interpolate(enter, [0, 1], [36, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}px)`}}>
        {fit.lines.map((line, index) => (
          <span className="fit-line" key={`${line}-${index}`}>
            {line}
          </span>
        ))}
      </p>
      <div className="signal-row">
        <div
          className="signal-pill"
          style={{boxShadow: `0 0 ${18 + audioPulse * 34}px rgba(255, 214, 10, ${0.28 * pulse})`}}
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
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const items = list(scene.props.items, data.cards.map((card) => card.value), 4);
  const activeIndex = items.length > 0 ? Math.floor(frame / Math.max(18, fps * 0.9)) % items.length : 0;
  return (
    <AbsoluteFill className="scene scene-bullets" style={{opacity: enter}}>
      <Kicker tone="cyan">{text(scene.props, ['kicker'], '拆成几步看', 18)}</Kicker>
      <h2>{text(scene.props, ['heading', 'title'], data.displayTitle, 56)}</h2>
      <div className="bullet-list">
        {items.map((item, index) => {
          const itemEnter = spring({frame: frame - 8 - index * 7, fps, config: {damping: 12, stiffness: 100}});
          const active = index === activeIndex;
          const drift = Math.sin(frame / 13 + index) * (active ? 8 : 3);
          return (
            <div
              className={`bullet-row${active ? ' bullet-row-active' : ''}`}
              key={`${item}-${index}`}
              style={{
                opacity: itemEnter,
                transform: `translateX(${(1 - itemEnter) * (42 - index * 5) + drift}px) scale(${active ? 1.025 : 1})`,
              }}
            >
              <span>{String(index + 1).padStart(2, '0')}</span>
              <strong>{item}</strong>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const CardScene: React.FC<SceneBlockProps> = ({scene, data, index}) => {
  const enter = useEnter(2);
  const frame = useCurrentFrame();
  const accent = CARD_ACCENTS[index % CARD_ACCENTS.length];
  const label = text(scene.props, ['label'], data.cards[index]?.label || '证据', 18);
  const value = text(scene.props, ['value'], data.cards[index]?.value || data.displayTitle, 48);
  const detail = optionalText(scene.props, ['detail'], data.cards[index]?.detail || data.summary, 120);
  const floatY = Math.sin(frame / 18 + index) * 12;
  const scan = (frame * 2 + index * 31) % 140;
  return (
    <AbsoluteFill className="scene scene-card" style={{opacity: enter}}>
      <div className="card-index" style={{color: accent}}>
        {String(index + 1).padStart(2, '0')}
      </div>
      <div
        className="big-card"
        style={{
          borderLeftColor: accent,
          background: `linear-gradient(90deg, rgba(10, 14, 20, 0.72) 0%, rgba(10, 14, 20, 0.72) ${scan - 14}%, color-mix(in srgb, ${accent} 18%, rgba(10, 14, 20, 0.72)) ${scan}%, rgba(10, 14, 20, 0.72) ${scan + 14}%)`,
          transform: `translate(${interpolate(enter, [0, 1], [40, 0])}px, ${floatY}px)`,
        }}
      >
        <div className="big-card-label" style={{color: accent}}>{label}</div>
        <div className="big-card-value">{value}</div>
        <div className="big-card-detail">{detail}</div>
      </div>
    </AbsoluteFill>
  );
};

const CompareScene: React.FC<SceneBlockProps> = ({scene, data}) => {
  const enter = useEnter(2);
  const frame = useCurrentFrame();
  const leftActive = Math.sin(frame / 22) >= 0;
  return (
    <AbsoluteFill className="scene scene-compare" style={{opacity: enter}}>
      <Kicker>{text(scene.props, ['kicker'], '别混在一起', 18)}</Kicker>
      <h2>{text(scene.props, ['heading', 'title'], data.displayTitle, 56)}</h2>
      <div className="compare-grid">
        <div className={leftActive ? 'compare-active' : ''} style={{transform: `translateY(${leftActive ? -10 : 4}px)`}}>
          <span>{text(scene.props, ['leftLabel'], '已知', 14)}</span>
          <strong>{text(scene.props, ['left'], data.cards[0]?.detail || data.summary, 90)}</strong>
        </div>
        <div className={!leftActive ? 'compare-active' : ''} style={{transform: `translateY(${!leftActive ? -10 : 4}px)`}}>
          <span>{text(scene.props, ['rightLabel'], '待证', 14)}</span>
          <strong>{text(scene.props, ['right'], data.verificationNextStep, 90)}</strong>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const CompareTableScene: React.FC<SceneBlockProps> = ({scene, data}) => {
  const enter = useEnter(2);
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const rows = list(
    scene.props.rows || scene.props.items,
    data.cards.slice(0, 4).map((card) => `${card.label}|${card.value}|${card.detail}`),
    4,
  );
  const activeIndex = rows.length > 0 ? Math.floor(frame / Math.max(18, fps * 0.8)) % rows.length : 0;
  return (
    <AbsoluteFill className="scene scene-compare-table" style={{opacity: enter}}>
      <Kicker>{text(scene.props, ['kicker'], '横向比较', 18)}</Kicker>
      <h2>{text(scene.props, ['heading', 'title'], data.displayTitle, 56)}</h2>
      <div className="compare-table">
        <div className="compare-table-head">
          <span>维度</span>
          <span>{text(scene.props, ['leftLabel'], '当前方案', 14)}</span>
          <span>{text(scene.props, ['rightLabel'], '验证边界', 14)}</span>
        </div>
        {rows.map((row, index) => {
          const [label, left, right] = splitRow(row, index);
          const itemEnter = spring({frame: frame - 10 - index * 8, fps, config: {damping: 12, stiffness: 100}});
          const active = index === activeIndex;
          return (
            <div
              className={`compare-table-row${active ? ' compare-table-row-active' : ''}`}
              key={`${label}-${index}`}
              style={{
                opacity: itemEnter,
                transform: `translateY(${(1 - itemEnter) * (24 - index * 3) + (active ? -8 : 0)}px) scale(${active ? 1.012 : 1})`,
              }}
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
  const {fps} = useVideoConfig();
  const prompt = text(scene.props, ['prompt'], '$', 8);
  const lines = list(scene.props.lines || scene.props.commands || scene.props.items, [
    'clone / install',
    'run quick start',
    'inspect examples',
    'check tests',
  ], 5);
  const activeIndex = lines.length > 0 ? Math.floor(frame / Math.max(20, fps * 0.85)) % lines.length : 0;
  return (
    <AbsoluteFill className="scene scene-terminal" style={{opacity: enter}}>
      <Kicker tone="cyan">{text(scene.props, ['kicker'], '把它放进终端看', 18)}</Kicker>
      <div className="terminal-window" style={{
        boxShadow: `0 0 ${24 + audioPulse * 36}px rgba(114, 231, 255, 0.16)`,
        transform: `translate(${interpolate(frame, [0, 900], [0, -40])}px, ${interpolate(frame, [0, 900], [0, -20])}px) scale(${interpolate(frame, [0, 900], [1.02, 1.07])})`
      }}>
        <div className="terminal-bar">
          <div className="terminal-lights"><span /><span /><span /></div>
          <strong>{text(scene.props, ['title', 'heading'], data.displayTitle, 42)}</strong>
        </div>
        <div className="terminal-body">
          {lines.map((line, index) => {
            const delay = index * 16;
            const reveal = Math.max(0, Math.min(Array.from(line).length, Math.floor((frame - delay) / 1.5)));
            const rendered = Array.from(line).slice(0, reveal).join('');
            const active = index === activeIndex;
            return (
              <div
                className={`terminal-line${active ? ' terminal-line-active' : ''}`}
                key={`${line}-${index}`}
                style={{transform: `translateX(${active ? 10 + Math.sin(frame / 8) * 6 : 0}px)`}}
              >
                <span>{prompt}</span>
                <code>{rendered || ' '}{active ? <b className="terminal-cursor">_</b> : null}</code>
              </div>
            );
          })}
          <div className="terminal-status">verified boundary: source-backed, not hype</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

const FlowScene: React.FC<SceneBlockProps> = ({scene, data, audioPulse}) => {
  const enter = useEnter(2);
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const nodes = list(scene.props.nodes || scene.props.steps || scene.props.items, ['输入', '核心模块', '输出', '验证门槛'], 5);
  const activeIndex = nodes.length > 0 ? Math.floor(frame / Math.max(22, fps * 0.9)) % nodes.length : 0;
  const railProgress = nodes.length > 1 ? Math.min(1, (activeIndex + (frame % Math.max(22, fps * 0.9)) / Math.max(22, fps * 0.9)) / (nodes.length - 1)) : 1;
  return (
    <AbsoluteFill className="scene scene-flow" style={{opacity: enter}}>
      <Kicker tone="cyan">{text(scene.props, ['kicker'], '机制怎么跑', 18)}</Kicker>
      <h2>{text(scene.props, ['heading', 'title'], data.displayTitle, 56)}</h2>
      <div className="flow-diagram" style={{boxShadow: `0 0 ${28 + audioPulse * 32}px rgba(114, 231, 255, 0.14)`}}>
        <div className="flow-rail">
          <div className="flow-rail-fill" style={{width: `${railProgress * 100}%`}} />
          <div className="flow-packet" style={{left: `${railProgress * 100}%`, transform: `translate(-50%, ${Math.sin(frame / 8) * 8}px) scale(${0.92 + audioPulse * 0.18})`}} />
        </div>
        <div className="flow-steps">
          {nodes.map((node, index) => {
            const itemEnter = spring({frame: frame - 6 - index * 6, fps, config: {damping: 12, stiffness: 100}});
            const active = index === activeIndex;
            return (
              <div className="flow-step" key={`${node}-${index}`}>
                <div
                  className={`flow-node${active ? ' flow-node-active' : ''}`}
                  style={{
                    opacity: interpolate(itemEnter, [0, 1], [0.35, 1]),
                    transform: `translateY(${(1 - itemEnter) * (28 - index * 4) + (active ? -14 + Math.sin(frame / 10) * 6 : 0)}px) scale(${active ? 1.06 : 1})`,
                  }}
                >
                  <span>{String(index + 1).padStart(2, '0')}</span>
                  <strong>{node}</strong>
                </div>
                {index < nodes.length - 1 ? <div className="flow-arrow">→</div> : null}
              </div>
            );
          })}
        </div>
      </div>
      <p className="flow-caption">{text(scene.props, ['caption', 'detail', 'summary'], '把机制画出来，才不是把文字贴到屏幕上。', 80)}</p>
    </AbsoluteFill>
  );
};

const ChartScene: React.FC<SceneBlockProps> = ({scene, data, audioPulse}) => {
  const enter = useEnter(2);
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const series = numericSeries(scene.props.points || scene.props.items, [18, 36, 52, 71, 88]);
  const max = Math.max(...series, 1);
  const min = Math.min(...series, 0);
  const range = Math.max(1, max - min);
  const progress = Math.max(0, Math.min(1, interpolate(enter, [0, 1], [0.05, 1])));
  const activeIndex = series.length > 0 ? Math.floor(frame / Math.max(18, fps * 0.75)) % series.length : 0;
  const scanX = 80 + ((frame * 9) % 760);
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
          <p>{text(scene.props, ['label'], '热度只当信号，结论要看验证路径。', 48)}</p>
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
          <line className="chart-scan-line" x1={scanX} x2={scanX} y1="56" y2="318" />
          {points.map((point, index) => (
            <g key={`${point.x}-${index}`} style={{opacity: index / Math.max(1, points.length - 1) <= progress ? 1 : 0}}>
              <circle className={index === activeIndex ? 'chart-dot chart-dot-active' : 'chart-dot'} cx={point.x} cy={point.y} r={10 + audioPulse * 3 + (index === activeIndex ? 5 + Math.sin(frame / 7) * 3 : 0)} />
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
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
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
  const activeIndex = rows.length > 0 ? Math.floor(frame / Math.max(18, fps * 0.75)) % rows.length : 0;
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
          {rows.map((row, index) => {
            const itemEnter = spring({frame: frame - 8 - index * 7, fps, config: {damping: 12, stiffness: 100}});
            const active = index === activeIndex;
            return (
              <div
                className={`diff-row diff-${row.kind}${active ? ' diff-row-active' : ''}`}
                key={`${row.kind}-${row.line}-${index}`}
                style={{
                  opacity: interpolate(itemEnter, [0, 1], [0.35, 1]),
                  transform: `translateX(${(1 - itemEnter) * 34 + (active ? 12 + Math.sin(frame / 9) * 5 : 0)}px)`,
                }}
              >
                <span>{row.kind === 'add' ? '+' : '-'}</span>
                <code>{row.line}</code>
              </div>
            );
          })}
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
      <div className="cta-footer">{optionalText(scene.props, ['footer'], data.verificationNextStep || data.footer, 80)}</div>
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// Engineering-theme scenes (SightLine-style: pure black + monospace + minimal)
// ---------------------------------------------------------------------------

/**
 * CodeBlockScene: renders a small file in an IDE-like window with one line
 * highlighted at a time. The visual is intentionally austere — the only
 * "decoration" is the active-line indicator and the tab dot.
 */
const CodeBlockScene: React.FC<SceneBlockProps> = ({scene, data, index}) => {
  const enter = useEnter(2);
  const frame = useCurrentFrame();
  const filename = text(scene.props, ['filename'], 'engine.py', 32);
  const lines = codeLines(scene.props.lines || scene.props.code || scene.props.items, [
    'def process(input):',
    '    context = gather(input)',
    '    return decide(context)',
  ], 14);
  // Walk the highlight one line at a time; allow manual override via prop.
  const autoHighlight = Math.floor(frame / 22) % Math.max(lines.length, 1);
  const highlight =
    typeof scene.props.highlight === 'number'
      ? Math.min(Math.max(Math.floor(scene.props.highlight), 0), Math.max(lines.length - 1, 0))
      : autoHighlight;
  const title = text(scene.props, ['title'], data.displayTitle, 60);
  const detail = optionalText(scene.props, ['detail'], data.summary, 110);
  return (
    <AbsoluteFill className="scene scene-code-block" style={{opacity: enter}}>
      <div className="act-tag">
        <span className="act-tag-num">ACT {typeof scene.props.act === 'number' ? scene.props.act : index + 1}</span>
        <span className="act-tag-name">— {text(scene.props, ['actLabel'], 'THE ENGINE', 18)}</span>
      </div>
      <div className="code-window">
        <div className="code-tab">
          <span className="code-tab-dot" />
          <strong>{filename}</strong>
        </div>
        <pre className="code-body">
          {lines.map((line, i) => (
            <div
              className={`code-line${i === highlight ? ' code-line-active' : ''}`}
              key={`${i}-${line}`}
              style={{
                opacity: interpolate(enter, [0, 1], [0.4, 1]),
              }}
            >
              <span className="code-line-num">{String(i + 1).padStart(2, '0')}</span>
              <code>{line || ' '}</code>
            </div>
          ))}
        </pre>
      </div>
      {(title || detail) ? (
        <div className="feature-caption">
          {title ? <strong>{title}</strong> : null}
          {detail ? <span>{detail}</span> : null}
        </div>
      ) : null}
    </AbsoluteFill>
  );
};

/**
 * NodeGraphScene: a hub-and-spoke architecture diagram. The center carries the
 * orchestrator/system name; the surrounding nodes are sub-components. Mirrors
 * the SightLine "Agent Architecture" frame (1 orchestrator + 6 specialists).
 */
const NodeGraphScene: React.FC<SceneBlockProps> = ({scene, data, index}) => {
  const enter = useEnter(2);
  const frame = useCurrentFrame();
  const nodes = list(scene.props.nodes || scene.props.items, [
    'Vision Agent', 'OCR Agent', 'Face Agent', 'Memory Agent', 'Navigation Agent', 'Search Agent',
  ], 8, 18);
  // Optional per-node sub-labels (model name, latency, etc).
  const subs = list(scene.props.subs || [], [], nodes.length, 18);
  // Walk highlight on a slow cadence; the active node also gets a stronger ring.
  const autoActive = nodes.length > 0 ? Math.floor(frame / 26) % nodes.length : 0;
  const active = typeof scene.props.active === 'number' ? scene.props.active : autoActive;
  const center = text(scene.props, ['center', 'title'], data.displayTitle, 28);
  const centerSub = text(scene.props, ['centerSub', 'powered'], 'powered by', 18);
  const viewBox = 1000;
  const cx = 500;
  const cy = 320;
  const radiusX = 290;
  const radiusY = 220;
  return (
    <AbsoluteFill className="scene scene-node-graph" style={{opacity: enter}}>
      <div className="act-tag">
        <span className="act-tag-num">ACT {typeof scene.props.act === 'number' ? scene.props.act : index + 1}</span>
        <span className="act-tag-name">— {text(scene.props, ['actLabel'], 'THE ARCHITECTURE', 22)}</span>
      </div>
      <svg className="node-graph-svg" viewBox={`0 0 ${viewBox} 640`} role="img">
        {nodes.map((node, i) => {
          const angle = (i / Math.max(nodes.length, 1)) * 2 * Math.PI - Math.PI / 2;
          const x = cx + Math.cos(angle) * radiusX;
          const y = cy + Math.sin(angle) * radiusY;
          return (
            <g key={`${i}-${node}`}>
              <line className="spoke" x1={cx} y1={cy} x2={x} y2={y} />
              <circle
                className={i === active ? 'node-ring node-ring-active' : 'node-ring'}
                cx={x}
                cy={y}
                r="48"
              />
              <text className="node-title" x={x} y={y - 2} textAnchor="middle">
                {node}
              </text>
              {subs[i] ? (
                <text className="node-sub" x={x} y={y + 18} textAnchor="middle">
                  {subs[i]}
                </text>
              ) : null}
            </g>
          );
        })}
        <circle className="center-ring" cx={cx} cy={cy} r="74" />
        <text className="center-title" x={cx} y={cy - 2} textAnchor="middle">
          {center}
        </text>
        <text className="center-sub" x={cx} y={cy + 22} textAnchor="middle">
          {centerSub}
        </text>
      </svg>
    </AbsoluteFill>
  );
};

/**
 * DecisionTableScene: a two-column "Rules → Output" grid. Mirrors SightLine's
 * Level-of-Detail Engine frame (six rules cascading into LOD categories).
 */
const DecisionTableScene: React.FC<SceneBlockProps> = ({scene, data, index}) => {
  const enter = useEnter(2);
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  // Rules can come as "R1 | High motion → Safety" rows OR as parallel arrays
  // (rules: ["High motion → Safety", ...], tags: ["R1", ...]).
  const rawRules = Array.isArray(scene.props.rules)
    ? (scene.props.rules as unknown[]).map((item) => text({item}, ['item'], '', 72))
    : list(scene.props.rules, ['High motion → Safety', 'Noise > threshold → Safety'], 8, 72);
  const tags = list(scene.props.tags || [], [], rawRules.length);
  const categories = list(scene.props.categories, ['LOD 1: Safety', 'LOD 2: Balanced', 'LOD 3: Detailed'], 4, 36);
  const subs = list(scene.props.categorySubs || [], [], categories.length, 42);
  // Walk the rule/category pairs so they reveal in sync.
  const revealCount = Math.min(
    rawRules.length,
    Math.floor(interpolate(enter, [0, 1], [0, rawRules.length + 1])),
  );
  const title = text(scene.props, ['title', 'heading'], data.displayTitle, 60);
  return (
    <AbsoluteFill className="scene scene-decision-table" style={{opacity: enter}}>
      <div className="act-tag">
        <span className="act-tag-num">ACT {typeof scene.props.act === 'number' ? scene.props.act : index + 1}</span>
        <span className="act-tag-name">— {text(scene.props, ['actLabel'], 'THE ENGINE', 18)}</span>
      </div>
      {title ? <h2>{title}</h2> : null}
      <div className="decision-grid">
        <div className="decision-col">
          <span className="decision-col-label">Rules</span>
          {rawRules.map((rule, i) => {
            const rowEnter = spring({frame: frame - 6 - i * 5, fps, config: {damping: 12, stiffness: 100}});
            const visible = i < revealCount;
            return (
              <div
                className="decision-rule"
                key={`${i}-${rule}`}
                style={{
                  opacity: rowEnter,
                  transform: `translateX(${(1 - rowEnter) * 18}px)`,
                  visibility: visible ? 'visible' : 'hidden',
                }}
              >
                {tags[i] ? <span className="decision-rule-tag">{tags[i]}</span> : null}
                <span>{rule}</span>
              </div>
            );
          })}
        </div>
        <div className="decision-col">
          <span className="decision-col-label">Output</span>
          {categories.map((cat, i) => {
            const rowEnter = spring({frame: frame - 12 - i * 5, fps, config: {damping: 12, stiffness: 100}});
            return (
              <div
                className="decision-cat"
                key={`${i}-${cat}`}
                style={{
                  opacity: rowEnter,
                  transform: `translateX(${(1 - rowEnter) * -18}px)`,
                  // Default amber; first category red, last green for visual variety.
                  borderLeftColor: i === 0 ? '#ff5f56' : i === categories.length - 1 ? '#22c55e' : 'var(--accent)',
                }}
              >
                {cat}
                {subs[i] ? <span className="decision-cat-sub">{subs[i]}</span> : null}
              </div>
            );
          })}
        </div>
      </div>
    </AbsoluteFill>
  );
};

/**
 * ActCardScene: a momentary banner that announces the upcoming act. Designed
 * to feel like a chapter title card — sits in the middle of the canvas and
 * lasts only ~0.4s at 30fps (use weight 0.06).
 */
const ActCardScene: React.FC<SceneBlockProps> = ({scene}) => {
  const enter = useEnter(0);
  const eyebrow = text(scene.props, ['eyebrow', 'title'], 'Live Demo', 18);
  const detail = text(scene.props, ['detail', 'text', 'heading'], 'Adaptive Guidance', 64);
  const sub = optionalText(scene.props, ['sub'], '', 90);
  return (
    <AbsoluteFill className="scene scene-act-card" style={{opacity: enter}}>
      <div className="act-card" style={{transform: `scale(${interpolate(enter, [0, 1], [0.94, 1])})`}}>
        <span className="act-card-eyebrow">{eyebrow}</span>
        <span className="act-card-title">{detail}</span>
        {sub ? <span className="act-card-detail">{sub}</span> : null}
      </div>
    </AbsoluteFill>
  );
};

/**
 * ClosingScene: the final frame. Wordmark, one-line description, and a small
 * "built for" caption. The whole composition fades up; no transitions.
 */
const ClosingScene: React.FC<SceneBlockProps> = ({scene}) => {
  const enter = useEnter(0);
  const mark = text(scene.props, ['mark'], 'searchpo', 20);
  const sub = text(scene.props, ['sub'], 'engineering videos for AI builders', 48);
  const built = text(scene.props, ['built'], 'built for the agents that watch the world', 60);
  return (
    <AbsoluteFill className="scene scene-closing" style={{opacity: enter}}>
      <div className="closing-mark" style={{transform: `translateY(${interpolate(enter, [0, 1], [20, 0])}px)`}}>
        <span className="closing-wordmark">{mark}</span>
        <span className="closing-sub">{sub}</span>
        <span className="closing-built">{built}</span>
      </div>
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
    case 'code_block':
      return <CodeBlockScene {...props} />;
    case 'node_graph':
      return <NodeGraphScene {...props} />;
    case 'decision_table':
      return <DecisionTableScene {...props} />;
    case 'act_card':
      return <ActCardScene {...props} />;
    case 'closing':
      return <ClosingScene {...props} />;
    case 'quote':
      return <QuoteScene {...props} />;
    case 'cta':
      return <CtaScene {...props} />;
    case 'card':
    default:
      return <CardScene {...props} />;
  }
};
