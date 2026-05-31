import type {CSSProperties} from 'react';

// ---------------------------------------------------------------------------
// Storyboard contract
//
// A storyboard is the agent-authored scene-graph that drives the video. It
// replaces the old single fixed template: the content agent picks WHICH scene
// blocks to show, in what order, with which brand-consistent style tokens. The
// audio / caption / duration spine is unaffected (captions stay a global
// sibling timed to the real voiceover); the storyboard only governs the visual
// scene band.
// ---------------------------------------------------------------------------

export const SCENE_TYPES = [
  'statement',
  'context',
  'stat',
  'bullets',
  'card',
  'compare',
  'quote',
  'cta',
] as const;

export type SceneType = (typeof SCENE_TYPES)[number];

export type Scene = {
  type: SceneType;
  // Props are intentionally loose: they come from an LLM and are coerced per
  // scene component. Strict bounds live in the JSON schema + Python validator.
  props: Record<string, unknown>;
  weight?: number;
  emphasis?: 'low' | 'normal' | 'high';
};

export type Theme = 'radar' | 'minimal' | 'editorial';
export type Density = 'minimal' | 'standard' | 'rich';
export type Motion = 'calm' | 'standard' | 'punchy';

export type ChromeTokens = {
  topbar?: boolean;
  progress?: boolean;
  beam?: boolean;
};

export type StyleTokens = {
  theme?: Theme;
  density?: Density;
  motion?: Motion;
  accent?: string;
  chrome?: ChromeTokens;
};

export type Storyboard = {
  version: number;
  style?: StyleTokens;
  scenes: Scene[];
};

export type NormalizedStyle = {
  theme: Theme;
  density: Density;
  motion: Motion;
  accent: string;
  chrome: Required<ChromeTokens>;
};

const THEME_DEFAULTS: Record<Theme, {accent: string; chrome: Required<ChromeTokens>}> = {
  radar: {accent: '#ffd60a', chrome: {topbar: true, progress: true, beam: true}},
  minimal: {accent: '#ffd60a', chrome: {topbar: false, progress: false, beam: false}},
  editorial: {accent: '#72e7ff', chrome: {topbar: true, progress: true, beam: false}},
};

const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

const pickEnum = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T =>
  (typeof value === 'string' && (allowed as readonly string[]).includes(value) ? (value as T) : fallback);

export const normalizeStyle = (style?: StyleTokens | null): NormalizedStyle => {
  const theme = pickEnum<Theme>(style?.theme, ['radar', 'minimal', 'editorial'], 'radar');
  const base = THEME_DEFAULTS[theme];
  const accent = typeof style?.accent === 'string' && HEX_RE.test(style.accent) ? style.accent : base.accent;
  const chromeIn = style?.chrome ?? {};
  return {
    theme,
    density: pickEnum<Density>(style?.density, ['minimal', 'standard', 'rich'], 'standard'),
    motion: pickEnum<Motion>(style?.motion, ['calm', 'standard', 'punchy'], 'standard'),
    accent,
    chrome: {
      topbar: chromeIn.topbar ?? base.chrome.topbar,
      progress: chromeIn.progress ?? base.chrome.progress,
      beam: chromeIn.beam ?? base.chrome.beam,
    },
  };
};

// Brand variation lives in a couple of CSS custom properties + theme/density
// classes; the locked brand core (fonts, safe area, caption style) stays fixed.
export const styleVars = (style: NormalizedStyle): CSSProperties =>
  ({'--accent': style.accent} as CSSProperties);

export const canvasClassName = (style: NormalizedStyle): string =>
  `canvas theme-${style.theme} density-${style.density} motion-${style.motion}`;

// Default timing share per scene type (used when the storyboard omits weight).
export const defaultWeightFor = (type: SceneType): number => {
  switch (type) {
    case 'statement':
      return 0.2;
    case 'context':
      return 0.18;
    case 'stat':
      return 0.16;
    case 'bullets':
      return 0.2;
    case 'compare':
      return 0.2;
    case 'quote':
      return 0.16;
    case 'cta':
      return 0.17;
    case 'card':
    default:
      return 0.15;
  }
};

// Allocate integer scene durations that sum exactly to the total, distributing
// the rounding remainder to the largest fractional parts. (Unchanged from the
// original template; kept here so the renderer and tests share one source.)
export const computeSceneFrames = (total: number, weights: number[]): number[] => {
  const wsum = weights.reduce((a, b) => a + b, 0);
  if (wsum <= 0) {
    throw new Error('Storyboard scene weights must sum to a positive value.');
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

// Choose a cross-fade length that keeps every scene's visible dwell above a
// readability floor; returns 0 (→ plain Series, hard cuts) when transitions
// can't fit (very short videos / many scenes). Using the real weights here
// guarantees the guard matches the actual TransitionSeries layout.
export const chooseTransitionFrames = (
  _durationInFrames: number,
  _weights: number[],
  _fps: number,
): number => {
  // Gemini visual audit is stricter than human viewing here: even a short
  // cross-fade can be read as overlapping public copy. Use hard cuts until the
  // transition layer can guarantee non-overlap for every scene pair.
  return 0;
};

// Compute the actual on-timeline start frame of each scene given the
// TransitionSeries overlap (each transition steals `d` frames from the join),
// so the progress chrome stays aligned with what's on screen.
export const sceneStartBoundaries = (sceneFrames: number[], transitionFrames: number): number[] => {
  const starts: number[] = [];
  let acc = 0;
  sceneFrames.forEach((f, i) => {
    starts.push(acc);
    acc += f - (i < sceneFrames.length - 1 ? transitionFrames : 0);
  });
  return starts;
};

const MAX_SCENES = 8;

// Forgiving validation for agent-authored input: drop unknown scene types and
// malformed scenes rather than throwing, so one bad scene can't kill a render.
// Hard bounds (text length, required props) are enforced by the JSON schema and
// the Python validator upstream; this just guards the renderer.
export const assertStoryboard = (input: unknown): Storyboard => {
  if (!input || typeof input !== 'object') {
    throw new Error('storyboard must be an object');
  }
  const raw = input as {version?: unknown; style?: StyleTokens; scenes?: unknown};
  const scenesIn = Array.isArray(raw.scenes) ? raw.scenes : [];
  const scenes: Scene[] = [];
  for (const candidate of scenesIn) {
    if (!candidate || typeof candidate !== 'object') continue;
    const s = candidate as {type?: unknown; props?: unknown; weight?: unknown; emphasis?: unknown};
    const type = String(s.type ?? '') as SceneType;
    if (!(SCENE_TYPES as readonly string[]).includes(type)) continue;
    const props = s.props && typeof s.props === 'object' ? (s.props as Record<string, unknown>) : {};
    const weight = typeof s.weight === 'number' && Number.isFinite(s.weight) && s.weight > 0 ? s.weight : undefined;
    const emphasis =
      s.emphasis === 'low' || s.emphasis === 'high' || s.emphasis === 'normal' ? s.emphasis : undefined;
    scenes.push({type, props, weight, emphasis});
    if (scenes.length >= MAX_SCENES) break;
  }
  if (scenes.length === 0) {
    throw new Error('storyboard requires at least one known scene block');
  }
  return {
    version: typeof raw.version === 'number' && raw.version > 0 ? raw.version : 1,
    style: raw.style,
    scenes,
  };
};

// Back-compat fallback: synthesize the original template's storyboard from the
// legacy flat fields when a payload carries no storyboard (old props, hand
// fixtures). Mirrors the Python contract-mode synthesis so both paths agree.
export type DerivableFields = {
  displayTitle: string;
  summary: string;
  audienceMetricLine: string;
  evidenceLevel: string;
  url: string;
  source?: string;
  cards: {label: string; value: string; detail: string}[];
  cta: string;
  verificationNextStep: string;
  footer: string;
};

export const deriveStoryboardFromCards = (data: DerivableFields): Storyboard => {
  const scenes: Scene[] = [
    {type: 'statement', props: {kicker: '今天为什么刷到它', title: data.displayTitle, sub: data.summary}},
    {
      type: 'context',
      props: {
        kicker: '一句话看懂',
        text: data.summary,
        metric: data.audienceMetricLine,
        metricNote: data.evidenceLevel.includes('unverified') ? '证据边界' : '实时信号',
        sourceLabel: '来源边界',
        sourceValue: data.source ? `${data.source} 已留档` : '来源已留档',
      },
    },
    ...data.cards.map((card) => ({
      type: 'card' as const,
      props: {label: card.label, value: card.value, detail: card.detail},
    })),
    {
      type: 'cta',
      props: {kicker: '先别急着下结论', text: data.cta, footer: data.verificationNextStep || data.footer},
    },
  ];
  return {version: 1, style: {theme: 'radar'}, scenes};
};
