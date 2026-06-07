import React, {useMemo} from 'react';
import {AbsoluteFill, interpolate, spring} from 'remotion';
import type {AgentVisualProps} from '../AgentVisualTypes';

type CardLike = {
  label?: string;
  value?: string;
  detail?: string;
};

type SceneCopy = {
  kicker: string;
  title: string;
  body: string;
};

const palette = {
  bg: '#101927',
  bg2: '#142235',
  panel: '#182840',
  panel2: '#1d314f',
  line: 'rgba(207, 220, 239, 0.16)',
  text: '#f6f8fb',
  muted: '#a9b7c9',
  faint: 'rgba(246, 248, 251, 0.54)',
  cyan: '#6ee7ff',
  green: '#9cf6c3',
  amber: '#f4c95d',
  coral: '#ff8b66',
  blue: '#89a9ff',
};

const clean = (value: unknown, max = 96): string => {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!text) {
    return '';
  }
  return text.length > max ? `${text.slice(0, max - 1).trim()}...` : text;
};

const firstText = (...values: unknown[]): string => {
  for (const value of values) {
    const text = clean(value, 140);
    if (text) {
      return text;
    }
  }
  return '';
};

const repoSlugFrom = (url: string, title: string, source: string): string => {
  const joined = `${url} ${title} ${source}`;
  const match = joined.match(/github\.com\/([^/\s?#]+)\/([^/\s?#]+)/i);
  if (match) {
    return `${match[1]}/${match[2].replace(/\.git$/i, '')}`;
  }
  const slash = joined.match(/\b([a-z0-9_.-]+\/[a-z0-9_.-]+)\b/i);
  return slash ? slash[1] : clean(title || source, 42) || 'GitHub repository';
};

const collectWords = (text: string): string[] => {
  const matches = text.match(/[A-Za-z][A-Za-z0-9_.-]{2,}|[\u4e00-\u9fa5]{2,}/g) ?? [];
  return matches
    .map((item) => item.replace(/^https?:\/\//, '').replace(/[.,;:]+$/, ''))
    .filter((item) => !/^(github|https|source|official|public|topic|candidate)$/i.test(item));
};

const unique = (items: string[], max: number): string[] => {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const item of items) {
    const text = clean(item, 30);
    const key = text.toLowerCase();
    if (!text || seen.has(key)) {
      continue;
    }
    seen.add(key);
    result.push(text);
    if (result.length >= max) {
      break;
    }
  }
  return result;
};

const valueOr = (items: string[], fallback: string[]): string[] => {
  return items.length > 0 ? items : fallback;
};

const useRepoModel = (props: AgentVisualProps) => {
  const {data} = props;
  return useMemo(() => {
    const cards = Array.isArray(data.cards) ? data.cards as CardLike[] : [];
    const storyboardScenes = Array.isArray(data.storyboard?.scenes) ? data.storyboard.scenes : [];
    const storyboardText = storyboardScenes
      .flatMap((scene) => {
        const props = scene.props && typeof scene.props === 'object' ? Object.values(scene.props) : [];
        return [scene.type, ...props];
      })
      .join(' ');
    const cardText = cards.map((card) => `${card.label ?? ''} ${card.value ?? ''} ${card.detail ?? ''}`).join(' ');
    const slug = repoSlugFrom(data.url, data.displayTitle || data.title, data.source);
    const words = unique(
      [
        ...collectWords(slug),
        ...collectWords(data.metricLine || ''),
        ...collectWords(cardText),
        ...collectWords(storyboardText),
        ...collectWords(data.summary || ''),
      ],
      18,
    );
    const modules = valueOr(
      unique(words.filter((word) => /api|sdk|mcp|cli|server|client|core|docs|proxy|cache|route|compress|agent/i.test(word)), 6),
      ['README', 'API surface', 'runtime path', 'integration', 'verification'],
    );
    const claims = valueOr(
      cards
        .map((card) => firstText(card.value, card.label, card.detail))
        .filter(Boolean)
        .slice(0, 4),
      [
        clean(data.metricLine, 42) || 'source backed claim',
        'mechanism needs inspection',
        'fit depends on workload',
      ],
    );
    const details = valueOr(
      cards
        .map((card) => firstText(card.detail, card.label))
        .filter(Boolean)
        .slice(0, 5),
      [
        clean(data.summary, 64) || 'read the repo surface before adopting',
        clean(data.verificationNextStep, 64) || 'run a small verification path',
      ],
    );
    const rawMetric = clean(data.audienceMetricLine || data.metricLine, 48);
    const metric = /指定主题|待验证|source observation|operator/i.test(rawMetric)
      ? (claims.find((claim) => /\d/.test(claim)) || claims[0] || rawMetric)
      : rawMetric;
    const sceneCopies: SceneCopy[] = [
      {
        kicker: 'Problem frame',
        title: '模型调用前，先处理上下文压力',
        body: clean(data.summary, 130),
      },
      {
        kicker: 'Repo surface',
        title: '先看仓库表面，再看 README 声称',
        body: clean(details[0], 118),
      },
      {
        kicker: 'Mechanism map',
        title: '沿着数据路径看机制',
        body: clean(details[1] || data.metricLine, 118),
      },
      {
        kicker: 'Evidence boundary',
        title: '把声称和证据边界分开',
        body: clean(data.verificationNextStep || details[2], 118),
      },
      {
        kicker: 'Adoption call',
        title: '只在匹配的工作负载里采用',
        body: clean(data.cta || data.footer || details[3], 118),
      },
    ];
    return {
      slug,
      headline: clean(data.displayTitle || data.title || slug, 54),
      metric: clean(metric, 48),
      modules,
      claims,
      details,
      words,
      sceneCopies,
    };
  }, [data]);
};

const pct = (value: number) => `${Math.round(value * 100)}%`;

const clamp01 = (value: number) => Math.max(0, Math.min(1, value));

const Header: React.FC<{
  slug: string;
  active: number;
  total: number;
  enter: number;
  width: number;
}> = ({slug, active, total, enter, width}) => {
  const isNarrow = width < 1200;
  return (
    <div
      style={{
        height: isNarrow ? 104 : 86,
        display: 'grid',
        gridTemplateColumns: isNarrow ? '1fr' : 'minmax(0, 1fr) 520px',
        gap: 24,
        alignItems: 'center',
        opacity: enter,
      }}
    >
      <div style={{minWidth: 0}}>
        <div style={{fontSize: 13, color: palette.cyan, fontWeight: 800, letterSpacing: 0}}>
          GitHub repo explainer
        </div>
        <div
          style={{
            marginTop: 8,
            fontSize: isNarrow ? 38 : 31,
            color: palette.text,
            fontWeight: 850,
            lineHeight: 1.04,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {slug}
        </div>
      </div>
      {!isNarrow && (
        <div style={{display: 'grid', gridTemplateColumns: `repeat(${total}, 1fr)`, gap: 8}}>
          {Array.from({length: total}, (_, index) => {
            const hot = index === active;
            return (
              <div key={index} style={{height: 8, borderRadius: 99, background: hot ? palette.cyan : palette.line}}>
                <div
                  style={{
                    height: '100%',
                    width: hot ? '100%' : '0%',
                    borderRadius: 99,
                    background: hot ? `linear-gradient(90deg, ${palette.cyan}, ${palette.green})` : 'transparent',
                    opacity: hot ? 1 : 0,
                  }}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

const Narrative: React.FC<{
  copy: SceneCopy;
  metric: string;
  frame: number;
  fps: number;
  localFrame: number;
  isHorizontal: boolean;
}> = ({copy, metric, frame, fps, localFrame, isHorizontal}) => {
  const enter = spring({frame: localFrame, fps, config: {damping: 22, stiffness: 115}});
  const drift = Math.sin(frame / 72) * 4;
  return (
    <div
      style={{
        minWidth: 0,
        alignSelf: 'stretch',
        display: 'grid',
        gridTemplateRows: 'auto 1fr auto',
        gap: isHorizontal ? 24 : 18,
      }}
    >
      <div style={{opacity: enter, transform: `translateY(${(1 - enter) * 18}px)`}}>
        <div style={{fontSize: 15, color: palette.green, fontWeight: 850, marginBottom: 14}}>{copy.kicker}</div>
        <div
          style={{
            fontSize: isHorizontal ? 50 : 45,
            color: palette.text,
            fontWeight: 900,
            lineHeight: 1.02,
            letterSpacing: 0,
          }}
        >
          {copy.title}
        </div>
        <div
          style={{
            marginTop: 22,
            fontSize: isHorizontal ? 22 : 24,
            color: palette.muted,
            fontWeight: 520,
            lineHeight: 1.42,
          }}
        >
          {copy.body}
        </div>
      </div>
      <div
        style={{
          alignSelf: 'end',
          borderRadius: 24,
          border: `1px solid ${palette.line}`,
          background: 'rgba(255,255,255,0.045)',
          padding: '22px 24px',
          boxShadow: '0 24px 80px rgba(0,0,0,0.22)',
          transform: `translateY(${drift}px)`,
        }}
      >
        <div style={{fontSize: 12, color: palette.faint, fontWeight: 900, textTransform: 'uppercase'}}>primary metric</div>
        <div style={{marginTop: 9, fontSize: 29, color: palette.amber, fontWeight: 900, lineHeight: 1.06}}>
          {metric || 'source bounded'}
        </div>
      </div>
      <div style={{height: 2, background: palette.line, borderRadius: 99}}>
        <div style={{height: 2, width: pct(clamp01(localFrame / 210)), background: palette.green, borderRadius: 99}} />
      </div>
    </div>
  );
};

const Shell: React.FC<{
  children: React.ReactNode;
  localFrame: number;
  fps: number;
}> = ({children, localFrame, fps}) => {
  const enter = spring({frame: localFrame, fps, config: {damping: 24, stiffness: 105}});
  const sweepCycle = Math.max(1, fps * 8);
  const sweepPhase = (localFrame % sweepCycle) / sweepCycle;
  const sweepLeft = interpolate(sweepPhase, [0, 1], [-18, 104]);
  const sweepOpacity = interpolate(localFrame, [0, 18, 34], [0, 0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  return (
    <div
      style={{
        position: 'relative',
        height: '100%',
        minHeight: 0,
        borderRadius: 30,
        border: `1px solid ${palette.line}`,
        background: `linear-gradient(145deg, ${palette.panel}, ${palette.bg2})`,
        boxShadow: '0 32px 110px rgba(0,0,0,0.32)',
        overflow: 'hidden',
        opacity: enter,
        transform: `translateY(${(1 - enter) * 18}px) scale(${0.985 + enter * 0.015})`,
      }}
    >
      {children}
      <div
        style={{
          position: 'absolute',
          top: 56,
          bottom: 0,
          left: `${sweepLeft}%`,
          width: '26%',
          opacity: 0.68 * sweepOpacity,
          background:
            'linear-gradient(90deg, transparent 0%, rgba(110,231,255,0.08) 38%, rgba(156,246,195,0.07) 52%, transparent 100%)',
          mixBlendMode: 'screen',
          pointerEvents: 'none',
        }}
      />
    </div>
  );
};

const WindowTop: React.FC<{title: string; accent?: string}> = ({title, accent = palette.cyan}) => (
  <div
    style={{
      height: 56,
      padding: '0 22px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      borderBottom: `1px solid ${palette.line}`,
      color: palette.muted,
      fontSize: 14,
      fontWeight: 760,
    }}
  >
    <div style={{display: 'flex', alignItems: 'center', gap: 9}}>
      <span style={{width: 10, height: 10, borderRadius: 99, background: palette.coral}} />
      <span style={{width: 10, height: 10, borderRadius: 99, background: palette.amber}} />
      <span style={{width: 10, height: 10, borderRadius: 99, background: palette.green}} />
    </div>
    <span style={{color: accent}}>{title}</span>
  </div>
);

const ProblemScene: React.FC<{
  model: ReturnType<typeof useRepoModel>;
  frame: number;
  fps: number;
  localFrame: number;
}> = ({model, frame, fps, localFrame}) => {
  const rows = [
    '$ agent runs tool output',
    'logs + files + rag chunks enter context',
    `${model.slug} sits before the model call`,
    model.metric || 'measure the saved context before adoption',
  ];
  return (
    <Shell localFrame={localFrame} fps={fps}>
      <WindowTop title="problem trace" />
      <div style={{height: 'calc(100% - 56px)', display: 'grid', gridTemplateColumns: '1.1fr 0.9fr', gap: 22, padding: 28}}>
        <div style={{borderRadius: 22, background: '#0e1726', border: `1px solid ${palette.line}`, padding: 24}}>
          {rows.map((row, index) => {
            const enter = spring({frame: localFrame - index * 10, fps, config: {damping: 18, stiffness: 120}});
            return (
              <div
                key={row}
                style={{
                  color: index === 0 ? palette.green : palette.muted,
                  fontFamily: 'SFMono-Regular, Menlo, Consolas, monospace',
                  fontSize: 22,
                  lineHeight: 1.62,
                  opacity: enter,
                  transform: `translateX(${(1 - enter) * -22}px)`,
                }}
              >
                {row}
              </div>
            );
          })}
          <div
            style={{
              marginTop: 22,
              height: 2,
              width: pct(interpolate(localFrame, [28, 128], [0.08, 0.88], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})),
              background: `linear-gradient(90deg, ${palette.cyan}, ${palette.green})`,
              borderRadius: 99,
            }}
          />
        </div>
        <div style={{display: 'grid', gap: 18}}>
          {model.claims.slice(0, 3).map((claim, index) => {
            const enter = spring({frame: localFrame - 16 - index * 12, fps, config: {damping: 20, stiffness: 120}});
            return (
              <div
                key={claim}
                style={{
                  borderRadius: 20,
                  background: 'rgba(255,255,255,0.055)',
                  border: `1px solid ${index === 0 ? palette.cyan : palette.line}`,
                  padding: 22,
                  opacity: enter,
                  transform: `translateY(${(1 - enter) * 18}px)`,
                }}
              >
                <div style={{fontSize: 12, color: palette.faint, fontWeight: 850}}>signal {index + 1}</div>
                <div style={{marginTop: 8, fontSize: 26, color: index === 0 ? palette.cyan : palette.text, fontWeight: 850, lineHeight: 1.1}}>
                  {claim}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </Shell>
  );
};

const RepoSurfaceScene: React.FC<{
  model: ReturnType<typeof useRepoModel>;
  frame: number;
  fps: number;
  localFrame: number;
}> = ({model, frame, fps, localFrame}) => {
  const active = Math.min(model.modules.length - 1, Math.floor((frame / 70) % model.modules.length));
  return (
    <Shell localFrame={localFrame} fps={fps}>
      <WindowTop title="repo surface" accent={palette.green} />
      <div style={{height: 'calc(100% - 56px)', display: 'grid', gridTemplateColumns: '330px 1fr', gap: 24, padding: 28}}>
        <div style={{borderRadius: 24, background: '#0d1624', border: `1px solid ${palette.line}`, padding: 22}}>
          <div style={{fontSize: 14, color: palette.faint, fontWeight: 850, marginBottom: 18}}>source tree</div>
          {model.modules.slice(0, 6).map((module, index) => {
            const hot = index === active;
            return (
              <div
                key={`${module}-${index}`}
                style={{
                  height: 48,
                  display: 'grid',
                  gridTemplateColumns: '22px 1fr',
                  alignItems: 'center',
                  gap: 12,
                  color: hot ? palette.text : palette.muted,
                  fontSize: 18,
                  fontWeight: hot ? 820 : 620,
                  opacity: hot ? 1 : 0.68,
                }}
              >
                <span style={{width: 12, height: 12, borderRadius: 4, background: hot ? palette.green : palette.line}} />
                <span style={{whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{module}</span>
              </div>
            );
          })}
        </div>
        <div style={{borderRadius: 24, background: 'rgba(255,255,255,0.05)', border: `1px solid ${palette.line}`, padding: 28}}>
          <div style={{fontSize: 13, color: palette.cyan, fontWeight: 880}}>README to workflow</div>
          <div style={{marginTop: 18, fontSize: 42, color: palette.text, fontWeight: 900, lineHeight: 1.05}}>
            {model.headline}
          </div>
          <div style={{marginTop: 28, display: 'grid', gap: 16}}>
            {model.details.slice(0, 4).map((detail, index) => {
              const enter = spring({frame: localFrame - 18 - index * 9, fps, config: {damping: 20, stiffness: 120}});
              return (
                <div
                  key={detail}
                  style={{
                    minHeight: 58,
                    borderRadius: 18,
                    background: index === active % 4 ? 'rgba(110,231,255,0.11)' : 'rgba(255,255,255,0.035)',
                    border: `1px solid ${index === active % 4 ? 'rgba(110,231,255,0.38)' : palette.line}`,
                    color: palette.muted,
                    fontSize: 21,
                    fontWeight: 620,
                    lineHeight: 1.25,
                    padding: '16px 18px',
                    opacity: enter,
                    transform: `translateY(${(1 - enter) * 15}px)`,
                  }}
                >
                  {detail}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Shell>
  );
};

const MechanismScene: React.FC<{
  model: ReturnType<typeof useRepoModel>;
  frame: number;
  fps: number;
  localFrame: number;
}> = ({model, frame, fps, localFrame}) => {
  const steps = valueOr(model.modules.slice(0, 5), ['input', 'route', 'compress', 'verify', 'ship']);
  const progress = interpolate(localFrame, [20, 190], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const active = Math.min(steps.length - 1, Math.floor(progress * steps.length));
  return (
    <Shell localFrame={localFrame} fps={fps}>
      <WindowTop title="mechanism map" accent={palette.amber} />
      <div style={{height: 'calc(100% - 56px)', padding: 34, display: 'grid', gridTemplateRows: '1fr 190px', gap: 26}}>
        <div style={{position: 'relative', borderRadius: 26, background: '#0d1727', border: `1px solid ${palette.line}`, padding: 38}}>
          <svg width="100%" height="100%" viewBox="0 0 980 360" style={{display: 'block'}}>
            <path d="M98 184 H882" stroke="rgba(207,220,239,0.18)" strokeWidth="12" strokeLinecap="round" />
            <path d="M98 184 H882" stroke={palette.cyan} strokeWidth="5" strokeLinecap="round" strokeDasharray="784" strokeDashoffset={784 * (1 - progress)} />
            <circle cx={98 + 784 * progress} cy="184" r="16" fill={palette.green} />
            {steps.map((step, index) => {
              const x = 98 + (784 / Math.max(1, steps.length - 1)) * index;
              const hot = index <= active;
              const y = index % 2 === 0 ? 112 : 256;
              return (
                <g key={step}>
                  <line x1={x} x2={x} y1="184" y2={y + (index % 2 === 0 ? 42 : -42)} stroke={hot ? palette.cyan : 'rgba(207,220,239,0.16)'} strokeWidth="3" />
                  <rect x={x - 78} y={y - 34} width="156" height="68" rx="18" fill={hot ? 'rgba(110,231,255,0.13)' : 'rgba(255,255,255,0.045)'} stroke={hot ? palette.cyan : palette.line} strokeWidth="2" />
                  <text x={x} y={y + 6} textAnchor="middle" fill={hot ? palette.text : palette.muted} fontSize="20" fontWeight="800">
                    {step.slice(0, 16)}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
        <div style={{display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 18}}>
          {model.claims.slice(0, 3).map((claim, index) => (
            <div key={claim} style={{borderRadius: 22, background: 'rgba(255,255,255,0.05)', border: `1px solid ${palette.line}`, padding: 22}}>
              <div style={{fontSize: 12, color: [palette.cyan, palette.amber, palette.green][index], fontWeight: 900}}>checkpoint</div>
              <div style={{marginTop: 12, fontSize: 24, color: palette.text, fontWeight: 830, lineHeight: 1.08}}>{claim}</div>
            </div>
          ))}
        </div>
      </div>
    </Shell>
  );
};

const EvidenceScene: React.FC<{
  model: ReturnType<typeof useRepoModel>;
  frame: number;
  fps: number;
  localFrame: number;
}> = ({model, fps, localFrame}) => {
  const rows = valueOr(model.details.slice(0, 5), ['README claim', 'docs check', 'minimal sample', 'source boundary', 'production caveat']);
  return (
    <Shell localFrame={localFrame} fps={fps}>
      <WindowTop title="evidence boundary" accent={palette.blue} />
      <div style={{height: 'calc(100% - 56px)', padding: 32, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24}}>
        <div style={{borderRadius: 24, background: '#0d1624', border: `1px solid ${palette.line}`, padding: 26}}>
          <div style={{fontSize: 14, color: palette.faint, fontWeight: 850}}>claim ledger</div>
          <div style={{marginTop: 24, display: 'grid', gap: 16}}>
            {model.claims.slice(0, 4).map((claim, index) => {
              const fill = interpolate(localFrame, [25 + index * 12, 92 + index * 12], [0.18, 0.86 - index * 0.08], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              });
              return (
                <div key={claim}>
                  <div style={{display: 'flex', justifyContent: 'space-between', gap: 14, color: palette.text, fontSize: 20, fontWeight: 760}}>
                    <span>{claim}</span>
                    <span style={{color: palette.faint}}>source</span>
                  </div>
                  <div style={{marginTop: 10, height: 8, borderRadius: 99, background: 'rgba(255,255,255,0.08)'}}>
                    <div style={{height: 8, width: pct(fill), borderRadius: 99, background: `linear-gradient(90deg, ${palette.blue}, ${palette.green})`}} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <div style={{borderRadius: 24, background: 'rgba(255,255,255,0.05)', border: `1px solid ${palette.line}`, padding: 26}}>
          <div style={{fontSize: 14, color: palette.faint, fontWeight: 850}}>what still needs checking</div>
          <div style={{marginTop: 22, display: 'grid', gap: 13}}>
            {rows.map((row, index) => {
              const enter = spring({frame: localFrame - index * 8, fps, config: {damping: 18, stiffness: 120}});
              return (
                <div
                  key={row}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '34px 1fr',
                    gap: 13,
                    alignItems: 'center',
                    minHeight: 50,
                    opacity: enter,
                    transform: `translateX(${(1 - enter) * 18}px)`,
                  }}
                >
                  <div style={{width: 26, height: 26, borderRadius: 9, border: `2px solid ${palette.green}`, display: 'grid', placeItems: 'center', color: palette.green, fontSize: 16, fontWeight: 900}}>
                    {index + 1}
                  </div>
                  <div style={{fontSize: 21, color: palette.muted, fontWeight: 650, lineHeight: 1.16}}>{row}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Shell>
  );
};

const DecisionScene: React.FC<{
  model: ReturnType<typeof useRepoModel>;
  frame: number;
  fps: number;
  localFrame: number;
}> = ({model, fps, localFrame}) => {
  const fit = valueOr(model.words.slice(0, 4), ['agent workflow', 'repo evidence', 'local test', 'bounded rollout']);
  const risks = valueOr(model.details.slice(-4), ['benchmark yourself', 'inspect failure modes', 'avoid blind adoption', 'keep evidence boundary']);
  return (
    <Shell localFrame={localFrame} fps={fps}>
      <WindowTop title="adoption decision" accent={palette.green} />
      <div style={{height: 'calc(100% - 56px)', padding: 32, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24}}>
        <div style={{borderRadius: 26, background: 'rgba(156,246,195,0.07)', border: '1px solid rgba(156,246,195,0.28)', padding: 28}}>
          <div style={{fontSize: 15, color: palette.green, fontWeight: 900}}>good fit when</div>
          <div style={{marginTop: 24, display: 'grid', gap: 18}}>
            {fit.map((item, index) => {
              const enter = spring({frame: localFrame - 14 - index * 9, fps, config: {damping: 19, stiffness: 120}});
              return (
                <div key={item} style={{display: 'grid', gridTemplateColumns: '38px 1fr', gap: 14, alignItems: 'center', opacity: enter}}>
                  <div style={{width: 32, height: 32, borderRadius: 99, background: palette.green, color: '#102019', display: 'grid', placeItems: 'center', fontSize: 17, fontWeight: 950}}>
                    OK
                  </div>
                  <div style={{fontSize: 24, color: palette.text, fontWeight: 790, lineHeight: 1.08}}>{item}</div>
                </div>
              );
            })}
          </div>
        </div>
        <div style={{borderRadius: 26, background: 'rgba(255,139,102,0.065)', border: '1px solid rgba(255,139,102,0.24)', padding: 28}}>
          <div style={{fontSize: 15, color: palette.coral, fontWeight: 900}}>verify before shipping</div>
          <div style={{marginTop: 24, display: 'grid', gap: 18}}>
            {risks.map((item, index) => {
              const enter = spring({frame: localFrame - 18 - index * 9, fps, config: {damping: 19, stiffness: 120}});
              return (
                <div key={item} style={{display: 'grid', gridTemplateColumns: '38px 1fr', gap: 14, alignItems: 'center', opacity: enter}}>
                  <div style={{width: 32, height: 32, borderRadius: 11, border: `2px solid ${palette.coral}`, color: palette.coral, display: 'grid', placeItems: 'center', fontSize: 17, fontWeight: 950}}>
                    {index + 1}
                  </div>
                  <div style={{fontSize: 22, color: palette.muted, fontWeight: 700, lineHeight: 1.12}}>{item}</div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </Shell>
  );
};

export const PremiumRepoVisual: React.FC<AgentVisualProps> = (props) => {
  const {frame, fps, durationInFrames, progress, width, height} = props;
  const model = useRepoModel(props);
  const isHorizontal = width > height;
  const sceneCount = model.sceneCopies.length;
  const active = Math.min(sceneCount - 1, Math.floor(clamp01(progress) * sceneCount));
  const sceneStart = Math.floor((durationInFrames / sceneCount) * active);
  const localFrame = Math.max(0, frame - sceneStart);
  const localProgress = clamp01(localFrame / Math.max(1, durationInFrames / sceneCount));
  const enter = spring({frame, fps, config: {damping: 24, stiffness: 105}});
  const glow = interpolate(Math.sin(frame / 88), [-1, 1], [0.16, 0.32]);
  const copy = model.sceneCopies[active] ?? model.sceneCopies[0];

  const visual =
    active === 0 ? (
      <ProblemScene model={model} frame={frame} fps={fps} localFrame={localFrame} />
    ) : active === 1 ? (
      <RepoSurfaceScene model={model} frame={frame} fps={fps} localFrame={localFrame} />
    ) : active === 2 ? (
      <MechanismScene model={model} frame={frame} fps={fps} localFrame={localFrame} />
    ) : active === 3 ? (
      <EvidenceScene model={model} frame={frame} fps={fps} localFrame={localFrame} />
    ) : (
      <DecisionScene model={model} frame={frame} fps={fps} localFrame={localFrame} />
    );

  return (
    <AbsoluteFill
      style={{
        backgroundColor: palette.bg,
        color: palette.text,
        fontFamily: 'Inter, PingFang SC, SF Pro Display, system-ui, sans-serif',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: `radial-gradient(circle at 18% 18%, rgba(110,231,255,${glow}), transparent 28%), radial-gradient(circle at 88% 12%, rgba(156,246,195,0.16), transparent 24%), linear-gradient(180deg, #101927, #0d1523)`,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 72,
          right: 72,
          top: isHorizontal ? 52 : 64,
          bottom: isHorizontal ? 210 : 560,
          display: 'grid',
          gridTemplateRows: 'auto minmax(0, 1fr)',
          gap: isHorizontal ? 34 : 28,
          opacity: enter,
        }}
      >
        <Header slug={model.slug} active={active} total={sceneCount} enter={enter} width={width} />
        <div
          style={{
            minHeight: 0,
            display: 'grid',
            gridTemplateColumns: isHorizontal ? '480px minmax(0, 1fr)' : '1fr',
            gridTemplateRows: isHorizontal ? '1fr' : 'auto minmax(0, 1fr)',
            gap: isHorizontal ? 34 : 26,
          }}
        >
          <Narrative copy={copy} metric={model.metric} frame={frame} fps={fps} localFrame={localFrame} isHorizontal={isHorizontal} />
          <div
            style={{
              minHeight: 0,
              opacity: interpolate(localProgress, [0, 0.06, 0.94, 1], [0.2, 1, 1, 0.9], {
                extrapolateLeft: 'clamp',
                extrapolateRight: 'clamp',
              }),
            }}
          >
            {visual}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};
