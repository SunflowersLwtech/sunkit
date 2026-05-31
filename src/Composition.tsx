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
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import {Captions, type CaptionSegment} from './Captions';
import {useFontsReady} from './fonts';
import {SceneBlock} from './scenes/SceneBlocks';
import {
  assertStoryboard,
  canvasClassName,
  chooseTransitionFrames,
  computeSceneFrames,
  defaultWeightFor,
  deriveStoryboardFromCards,
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
  if (!props.storyboard && cards.length === 0) {
    throw new Error('SearchpoRadar requires either storyboard scenes or at least one legacy card.');
  }

  const base = {
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

  const storyboard = props.storyboard
    ? assertStoryboard(props.storyboard)
    : deriveStoryboardFromCards({
        displayTitle: base.displayTitle,
        summary: base.summary,
        audienceMetricLine: base.audienceMetricLine,
        evidenceLevel: base.evidenceLevel,
        url: base.url,
        cards: base.cards,
        cta: base.cta,
        verificationNextStep: base.verificationNextStep,
        footer: base.footer,
      });

  return {...base, storyboard};
};

const Background: React.FC<{beam: boolean; audioPulse: number}> = ({beam, audioPulse}) => {
  const frame = useCurrentFrame();
  const sweep = interpolate(frame % 150, [0, 150], [-45, 125]);
  return (
    <>
      <div className="noise" />
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
          presentation={fade({shouldFadeOutExitingScene: true})}
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

  return (
    <AbsoluteFill className={canvasClassName(style)} style={canvasStyle}>
      <Audio src={audioSrc} />
      <Background audioPulse={audioPulse} beam={style.chrome.beam} />
      {style.chrome.topbar ? <TopBar data={data} /> : null}
      {style.chrome.progress ? <SceneProgress boundaries={boundaries} total={durationInFrames} /> : null}

      {transitionFrames > 0
        ? renderTransitionSeries(data, sceneFrames, transitionFrames, style, audioPulse)
        : renderPlainSeries(data, sceneFrames, style, audioPulse)}

      <Captions segments={data.captions} />
      {posterOpacity > 0 ? <AutoCoverPoster data={data} opacity={posterOpacity} /> : null}
    </AbsoluteFill>
  );
};
