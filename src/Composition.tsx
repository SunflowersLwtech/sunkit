import type {CSSProperties, ReactNode} from 'react';
import {useMemo} from 'react';
import {useAudioData, visualizeAudio} from '@remotion/media-utils';
import {TransitionSeries, linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
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
import {slide} from '@remotion/transitions/slide';
import {HexGrid} from './components/VFX';
import {CinematicOverlay} from './CinematicOverlay';
import {Captions, type CaptionSegment} from './Captions';
import {useFontsReady} from './fonts';
import {AgentVisualGenerated} from './generated/AgentVisual.generated';
import {SceneBlock} from './scenes/SceneBlocks';
import {
  assertStoryboard,
  canvasClassName,
  chooseTransitionFrames,
  computeSceneFrames,
  defaultWeightFor,
  normalizeStyle,
  sceneStartBoundaries,
  styleVars,
  type Storyboard,
} from './storyboard';

export type Card = {
  label: string;
  value: string;
  detail: string;
};

export type Payload = {
  badge: string;
  title: string;
  displayTitle: string;
  speechTitle: string;
  summary: string;
  source: string;
  url: string;
  score: number | string | null;
  metricLine: string;
  audienceMetricLine: string;
  evidenceLevel: string;
  orientation: 'vertical' | 'horizontal';
  aspectRatio: '9:16' | '16:9';
  width: number;
  height: number;
  videoProfile: {
    duration_seconds?: number;
    orientation?: 'vertical' | 'horizontal';
    aspect_ratio?: '9:16' | '16:9';
    motion?: 'calm' | 'standard' | 'punchy';
    animation_style?: string;
    decision_reason?: string;
  };
  agentVisual?: {
    enabled?: boolean;
    mode?: 'react_runtime';
    render_mode?: 'overlay' | 'full_canvas';
    description?: string;
    module_code?: string;
    component_code?: string;
    css?: string;
    validation_errors?: string[];
    chapter_bridge?: boolean;
    motion_profile?: string;
  };
  agentVisualRequired?: boolean;
  qualityWarnings: string[];
  verificationNextStep: string;
  cards: Card[];
  storyboard: Storyboard;
  audioSrc: string;
  voiceoverText: string;
  captions: CaptionSegment[];
  durationInFrames: number;
  fps: number;
  cta: string;
  footer: string;
};

const fitText = (text: string, max = 96) => (text.length > max ? `${text.slice(0, max - 1)}...` : text);

const requireText = (value: string | null | undefined, field: string): string => {
  if (!value || !value.trim()) {
    throw new Error(`SearchpoRadar missing required prop: ${field}`);
  }
  return value;
};

const normalizeCards = (cards: Card[] | null | undefined): Card[] =>
  Array.isArray(cards)
    ? cards
        .filter((card) => card && typeof card === 'object')
        .map((card) => ({
          label: String(card.label || '').trim(),
          value: String(card.value || '').trim(),
          detail: String(card.detail || '').trim(),
        }))
        .filter((card) => card.label || card.value || card.detail)
    : [];

const requireCaptions = (captions: CaptionSegment[] | null | undefined): CaptionSegment[] => {
  if (!Array.isArray(captions) || captions.length === 0) {
    throw new Error('SearchpoRadar requires timed captions from scripts/build_captions.py.');
  }
  return captions;
};

export const normalizeDimensions = (props: Partial<Payload>): Pick<Payload, 'orientation' | 'aspectRatio' | 'width' | 'height'> => {
  const hintedOrientation = props.orientation === 'horizontal' || props.aspectRatio === '16:9' ? 'horizontal' : 'vertical';
  const width = typeof props.width === 'number' && Number.isFinite(props.width) && props.width > 0
    ? Math.round(props.width)
    : hintedOrientation === 'horizontal' ? 1920 : 1080;
  const height = typeof props.height === 'number' && Number.isFinite(props.height) && props.height > 0
    ? Math.round(props.height)
    : hintedOrientation === 'horizontal' ? 1080 : 1920;
  const orientation = width > height ? 'horizontal' : 'vertical';
  return {
    orientation,
    aspectRatio: orientation === 'horizontal' ? '16:9' : '9:16',
    width,
    height,
  };
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

  const cards = normalizeCards(props.cards);
  if (!props.storyboard) {
    throw new Error('SearchpoRadar requires storyboard scenes; legacy card fallback is not allowed.');
  }

  const base = {
    ...normalizeDimensions(props),
    badge: requireText(props.badge, 'badge'),
    title: requireText(props.title, 'title'),
    displayTitle: props.displayTitle?.trim() || requireText(props.title, 'title'),
    speechTitle: props.speechTitle?.trim() || requireText(props.title, 'title'),
    summary: requireText(props.summary, 'summary'),
    source: requireText(props.source, 'source'),
    url: requireText(props.url, 'url'),
    score: props.score ?? null,
    metricLine: requireText(props.metricLine, 'metricLine'),
    audienceMetricLine: props.audienceMetricLine?.trim() || requireText(props.metricLine, 'metricLine'),
    evidenceLevel: props.evidenceLevel?.trim() || 'source_observation_unverified',
    videoProfile: props.videoProfile ?? {},
    agentVisual: props.agentVisual ?? {enabled: false},
    agentVisualRequired: Boolean(props.agentVisualRequired),
    qualityWarnings: Array.isArray(props.qualityWarnings) ? props.qualityWarnings : [],
    verificationNextStep: props.verificationNextStep?.trim() || '下一步补充证据后再判断。',
    cards,
    audioSrc: requireText(props.audioSrc, 'audioSrc'),
    voiceoverText: requireText(props.voiceoverText, 'voiceoverText'),
    captions: requireCaptions(props.captions),
    durationInFrames: Math.round(durationInFrames),
    fps: Math.round(fps),
    cta: requireText(props.cta, 'cta'),
    footer: requireText(props.footer, 'footer'),
  };

  const storyboard = assertStoryboard(props.storyboard);

  return {...base, storyboard};
};

const Background: React.FC<{beam: boolean; audioPulse: number}> = ({beam, audioPulse}) => {
  const frame = useCurrentFrame();
  const sweep = interpolate(frame % 150, [0, 150], [-45, 125]);
  return (
    <>
      <AbsoluteFill className="composition-root">
      <div className="composition-bg">
        <HexGrid />
      </div>
      </AbsoluteFill>
      <div className="noise" />
      <div className="ambient-map" style={{opacity: 0.48 + audioPulse * 0.18}} />
      {beam ? (
        <div
          className="beam"
          style={{
            opacity: 0.7 + audioPulse * 0.25,
            transform: `translateX(${sweep}%) rotate(-14deg)`,
          }}
        />
      ) : null}
    </>
  );
};

const AudioWave: React.FC<{audioPulse: number}> = ({audioPulse}) => {
  const frame = useCurrentFrame();
  const bars = useMemo(() => Array.from({length: 18}, (_, index) => index), []);
  return (
    <div className="audio-wave">
      {bars.map((index) => {
        const wave = interpolate(Math.sin(frame / 7 + index * 0.7), [-1, 1], [0.35, 1]);
        return <span key={index} style={{transform: `scaleY(${0.25 + wave * 0.42 + audioPulse * 0.33})`}} />;
      })}
    </div>
  );
};

const TopBar: React.FC<{data: Payload}> = ({data}) => (
  <div className="topbar">
    <span>{requireText(data.badge, 'badge')}</span>
    <span className="topbar-source">{fitText(data.source, 18)}</span>
  </div>
);

const AutoCoverPoster: React.FC<{data: Payload; opacity: number}> = ({data, opacity}) => {
  const title = fitText(data.displayTitle || data.title, 54);
  const metric = fitText(data.audienceMetricLine || data.metricLine, 30);
  return (
    <div className="video-poster-overlay" style={{opacity}}>
      <div className="video-poster-top">
        <span>{requireText(data.badge, 'badge')}</span>
        <strong>searchpo radar</strong>
      </div>
      <div className="video-poster-kicker">今天为什么刷到它</div>
      <div className="video-poster-title">{title}</div>
      <div className="video-poster-metric">{metric}</div>
      <div className="video-poster-source">{fitText(data.source, 40)}</div>
    </div>
  );
};

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

const sceneText = (props: Record<string, unknown>, keys: string[], fallback = '', max = 96): string => {
  for (const key of keys) {
    const value = props[key];
    if (typeof value === 'string' && value.trim()) {
      const clean = value.replace(/\s+/g, ' ').trim();
      return fitText(clean, max);
    }
  }
  return fitText(fallback.replace(/\s+/g, ' ').trim(), max);
};

const sceneList = (value: unknown, fallback: string[], max = 4, itemMax = 42): string[] => {
  const raw = Array.isArray(value) ? value : fallback;
  const items = raw
    .map((item) => fitText(String(item ?? '').replace(/\s+/g, ' ').trim(), itemMax))
    .filter(Boolean)
    .slice(0, max);
  return items.length > 0 ? items : fallback.slice(0, max);
};

const sceneTypeLabel = (type: string): string => {
  const labels: Record<string, string> = {
    statement: '开场判断',
    context: '背景边界',
    stat: '数据观察',
    bullets: '要点拆解',
    card: '证据卡',
    compare: '对照取舍',
    compare_table: '对照表',
    terminal: '终端验证',
    flow: '机制流',
    chart: '指标图',
    code_diff: '代码差异',
    code_block: '代码片段',
    node_graph: '架构图',
    decision_table: '决策表',
    act_card: '章节卡',
    quote: '来源摘录',
    cta: '验证动作',
    closing: '收束结论',
  };
  return labels[type] ?? '章节';
};

const currentSceneIndex = (frame: number, boundaries: number[], total: number): number => {
  if (boundaries.length === 0 || total <= 0) {
    return 0;
  }
  let active = 0;
  for (let index = 0; index < boundaries.length; index += 1) {
    if (frame >= boundaries[index]) {
      active = index;
    }
  }
  return Math.min(active, boundaries.length - 1);
};

const ProviderChapterBridge: React.FC<{
  data: Payload;
  boundaries: number[];
  total: number;
  style: ReturnType<typeof normalizeStyle>;
  audioPulse: number;
}> = ({data, boundaries, total, style, audioPulse}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sceneIndex = currentSceneIndex(frame, boundaries, total);
  const scene = data.storyboard.scenes[sceneIndex] ?? data.storyboard.scenes[0];
  if (!scene) {
    return null;
  }
  const start = boundaries[sceneIndex] ?? 0;
  const end = sceneIndex + 1 < boundaries.length ? boundaries[sceneIndex + 1] : total;
  const localFrame = Math.max(0, frame - start);
  const localProgress = Math.min(1, Math.max(0, localFrame / Math.max(1, end - start)));
  const enter = spring({frame: localFrame, fps, config: {damping: 18, stiffness: 120}});
  const exit = interpolate(localProgress, [0.84, 1], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const palette = ['#ffd60a', '#72e7ff', '#ff8a5b', '#9cffd0', '#c7a6ff'];
  const accent = sceneIndex === 0 ? style.accent : palette[sceneIndex % palette.length];
  const isVertical = data.height >= data.width;
  const side = isVertical ? 34 : 52;
  const heading = sceneText(scene.props, ['kicker', 'title', 'heading', 'label'], sceneTypeLabel(scene.type), 28);

  return (
    <AbsoluteFill style={{zIndex: 4, pointerEvents: 'none'}}>
      <div style={{
        position: 'absolute',
        top: isVertical ? 42 : 34,
        right: side,
        width: isVertical ? 312 : 380,
        minHeight: isVertical ? 58 : 54,
        borderRadius: 18,
        padding: '10px 14px',
        background: 'rgba(12, 19, 30, 0.42)',
        border: `1px solid ${accent}80`,
        boxShadow: `0 16px 40px rgba(0,0,0,0.18), 0 0 ${10 + audioPulse * 10}px ${accent}26`,
        opacity: enter * exit * 0.82,
        transform: `translateY(${Math.round((1 - enter) * -14 + Math.sin(frame / 22) * 2)}px)`,
      }}>
        <div style={{display: 'grid', gridTemplateColumns: 'auto 1fr', alignItems: 'center', gap: 10}}>
          <div style={{width: 34, height: 34, borderRadius: 999, background: accent, color: '#172235', display: 'grid', placeItems: 'center', fontSize: 15, fontWeight: 960}}>
            {sceneIndex + 1}
          </div>
          <div style={{minWidth: 0}}>
            <div style={{fontSize: 11, color: 'rgba(255,253,244,0.58)', fontWeight: 900, textTransform: 'uppercase'}}>
              chapter / {data.storyboard.scenes.length}
            </div>
            <div style={{fontSize: 15, color: 'rgba(255,253,244,0.86)', fontWeight: 900, lineHeight: 1.05, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>
              {heading}
            </div>
          </div>
        </div>
      </div>

      <div style={{
        position: 'absolute',
        left: side,
        top: isVertical ? 172 : 116,
        display: 'grid',
        gridTemplateRows: `repeat(${data.storyboard.scenes.length}, 13px)`,
        gap: 8,
        opacity: 0.5,
      }}>
        {data.storyboard.scenes.map((item, index) => {
          const hot = index === sceneIndex;
          return (
            <div key={`${item.type}-${index}`} style={{width: hot ? 28 : 12, height: 12, borderRadius: 999, background: hot ? accent : 'rgba(255,253,244,0.34)', transform: `scale(${hot ? 1 + audioPulse * 0.1 : 1})`}} />
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const renderPlainSeries = (
  data: Payload,
  sceneFrames: number[],
  style: ReturnType<typeof normalizeStyle>,
  audioPulse: number,
): ReactNode => (
  <Series>
    {data.storyboard.scenes.map((scene, index) => (
      <Series.Sequence durationInFrames={sceneFrames[index]} key={`${scene.type}-${index}`}>
        <SceneBlock
          audioPulse={audioPulse}
          count={data.storyboard.scenes.length}
          data={data}
          index={index}
          scene={scene}
          style={style}
        />
      </Series.Sequence>
    ))}
  </Series>
);

const renderTransitionSeries = (
  data: Payload,
  sceneFrames: number[],
  transitionFrames: number,
  style: ReturnType<typeof normalizeStyle>,
  audioPulse: number,
): ReactNode => {
  const children: ReactNode[] = [];
  data.storyboard.scenes.forEach((scene, index) => {
    children.push(
      <TransitionSeries.Sequence durationInFrames={sceneFrames[index]} key={`${scene.type}-${index}`}>
        <SceneBlock
          audioPulse={audioPulse}
          count={data.storyboard.scenes.length}
          data={data}
          index={index}
          scene={scene}
          style={style}
        />
      </TransitionSeries.Sequence>,
    );
    if (index < data.storyboard.scenes.length - 1) {
      children.push(
        <TransitionSeries.Transition
          key={`transition-${index}`}
          presentation={slide({direction: 'from-right'})}
          timing={linearTiming({durationInFrames: transitionFrames})}
        />,
      );
    }
  });
  return <TransitionSeries>{children}</TransitionSeries>;
};

export const SearchpoRadar: React.FC<Partial<Payload>> = (props) => {
  useFontsReady();
  const data = assertPayload(props);
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const audioSrc = staticFile(data.audioSrc);
  const audioData = useAudioData(audioSrc);

  const style = normalizeStyle(data.storyboard.style);
  const weights = useMemo(
    () => data.storyboard.scenes.map((scene) => scene.weight ?? defaultWeightFor(scene.type)),
    [data.storyboard.scenes],
  );
  const transitionFrames = chooseTransitionFrames(durationInFrames, weights, fps);
  const sceneFrames = useMemo(
    () => computeSceneFrames(durationInFrames + (data.storyboard.scenes.length - 1) * transitionFrames, weights),
    [data.storyboard.scenes.length, durationInFrames, transitionFrames, weights],
  );
  const boundaries = useMemo(
    () => sceneStartBoundaries(sceneFrames, transitionFrames),
    [sceneFrames, transitionFrames],
  );

  const audioPulse =
    style.motion === 'punchy' && audioData
      ? Math.min(
          1,
          Math.max(
            0,
            ...visualizeAudio({
              audioData,
              frame,
              fps,
              numberOfSamples: 16,
            }),
          ),
        )
      : interpolate(Math.sin(frame / 9), [-1, 1], [0.35, 1]);

  const introOpacity = interpolate(frame, [0, 8], [0.94, 1], {extrapolateRight: 'clamp'});
  const outroOpacity = interpolate(
    frame,
    [durationInFrames - 24, durationInFrames - 6],
    [1, 0],
    {extrapolateLeft: 'clamp'},
  );
  const masterOpacity = Math.min(introOpacity, outroOpacity);
  const canvasStyle = {
    ...styleVars(style),
    '--audio-pulse': audioPulse,
    opacity: masterOpacity,
  } as CSSProperties;
  const posterOpacity = interpolate(frame, [0, Math.round(fps * 0.45), Math.round(fps * 0.95)], [1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const useAgentVisual = data.agentVisual?.enabled === true;
  const isOverlay = useAgentVisual && data.agentVisual?.render_mode === 'overlay';
  const showCinematicOverlay = !useAgentVisual && style.theme !== 'engineering';
  const showProviderChapterBridge =
    useAgentVisual &&
    !isOverlay &&
    data.agentVisual?.chapter_bridge === true;

  return (
    <AbsoluteFill className={canvasClassName(style, data.orientation)} style={canvasStyle}>
      <Audio src={audioSrc} />
      {(!useAgentVisual || isOverlay) && (
        <>
          <Background audioPulse={audioPulse} beam={style.chrome.beam} />
          {style.chrome.topbar ? <TopBar data={data} /> : null}
          {style.chrome.progress ? <SceneProgress boundaries={boundaries} total={durationInFrames} /> : null}
          <AudioWave audioPulse={audioPulse} />

          {transitionFrames > 0
            ? renderTransitionSeries(data, sceneFrames, transitionFrames, style, audioPulse)
            : renderPlainSeries(data, sceneFrames, style, audioPulse)}
        </>
      )}
      {useAgentVisual && (
        <AgentVisualGenerated
          audioPulse={audioPulse}
          data={data}
          durationInFrames={durationInFrames}
          fps={fps}
          frame={frame}
          height={data.height}
          progress={durationInFrames > 0 ? frame / durationInFrames : 0}
          width={data.width}
        />
      )}
      {showProviderChapterBridge ? (
        <ProviderChapterBridge
          audioPulse={audioPulse}
          boundaries={boundaries}
          data={data}
          style={style}
          total={durationInFrames}
        />
      ) : null}

      {!useAgentVisual && posterOpacity > 0 ? <AutoCoverPoster data={data} opacity={posterOpacity} /> : null}
      {showCinematicOverlay ? <CinematicOverlay /> : null}
      <Captions segments={data.captions} />
    </AbsoluteFill>
  );
};
