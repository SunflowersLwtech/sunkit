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
  'compare_table',
  'terminal',
  'flow',
  'chart',
  'code_diff',
  'code_block',
  'node_graph',
  'decision_table',
  'act_card',
  'closing',
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

export type Theme = 'radar' | 'minimal' | 'editorial' | 'engineering';
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
  // Engineering theme: pure-black canvas + monospace, no decorative noise. The
  // visual language comes from code/node-graph/decision-table scenes themselves,
  // not from background gradients. See theme-engineering overrides in styles.css.
  engineering: {accent: '#f59e0b', chrome: {topbar: false, progress: false, beam: false}},
};

const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

const pickEnum = <T extends string>(value: unknown, allowed: readonly T[], fallback: T): T =>
  (typeof value === 'string' && (allowed as readonly string[]).includes(value) ? (value as T) : fallback);

export const normalizeStyle = (style?: StyleTokens | null): NormalizedStyle => {
  const theme = pickEnum<Theme>(style?.theme, ['radar', 'minimal', 'editorial', 'engineering'], 'radar');
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

export const canvasClassName = (style: NormalizedStyle, orientation: 'vertical' | 'horizontal' = 'vertical'): string =>
  `canvas theme-${style.theme} density-${style.density} motion-${style.motion} aspect-${orientation}`;

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
    case 'compare_table':
      return 0.2;
    case 'terminal':
      return 0.22;
    case 'flow':
      return 0.22;
    case 'chart':
      return 0.18;
    case 'code_diff':
      return 0.22;
    // Engineering-theme scenes: long enough to read, short enough to keep pace.
    case 'code_block':
      return 0.14;
    case 'node_graph':
      return 0.18;
    case 'decision_table':
      return 0.2;
    case 'act_card':
      return 0.06;
    case 'closing':
      return 0.09;
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

const MAX_SCENES = 24;

const requiredSceneKeys: Record<SceneType, string[]> = {
  statement: ['title', 'heading', 'headline', 'text'],
  context: ['text', 'summary', 'detail'],
  stat: ['value', 'stat', 'label', 'heading'],
  bullets: ['heading', 'title', 'items'],
  card: ['value', 'detail', 'title', 'heading', 'text', 'summary', 'label', 'kicker'],
  compare: ['left', 'right', 'title', 'heading', 'text', 'summary', 'items'],
  compare_table: ['rows', 'items'],
  terminal: ['lines', 'commands', 'items', 'title', 'heading', 'text', 'summary'],
  flow: ['nodes', 'steps', 'items'],
  chart: ['value', 'stat', 'points', 'items'],
  code_diff: ['additions', 'added', 'removals', 'removed', 'items', 'lines', 'changes', 'diff', 'title', 'heading'],
  // Structured engineering scenes must carry structured content, not just a title.
  code_block: ['lines', 'code', 'items'],
  node_graph: ['nodes', 'items'],
  decision_table: ['rules', 'items'],
  act_card: ['title', 'detail', 'heading', 'text'],
  closing: ['mark', 'title', 'heading'],
  quote: ['quote', 'text'],
  cta: ['text'],
};

const hasRequiredSceneText = (type: SceneType, props: Record<string, unknown>): boolean =>
  requiredSceneKeys[type].some((key) => {
    const value = props[key];
    if (Array.isArray(value)) {
      return value.some((item) => String(item ?? '').trim());
    }
    return typeof value === 'string' && value.trim().length > 0;
  });

// Renderer-side validation mirrors the Python contract and fails closed. Bad
// provider scene graphs must not be silently rewritten into generic content.
export const assertStoryboard = (input: unknown): Storyboard => {
  if (!input || typeof input !== 'object') {
    throw new Error('storyboard must be an object');
  }
  const raw = input as {version?: unknown; style?: StyleTokens; scenes?: unknown};
  if (!Array.isArray(raw.scenes)) {
    throw new Error('storyboard.scenes must be an array');
  }
  if (raw.scenes.length > MAX_SCENES) {
    throw new Error(`storyboard.scenes must contain at most ${MAX_SCENES} scenes`);
  }
  const scenes: Scene[] = [];
  for (const [index, candidate] of raw.scenes.entries()) {
    if (!candidate || typeof candidate !== 'object') {
      throw new Error(`storyboard scene ${index + 1} must be an object`);
    }
    const s = candidate as {type?: unknown; props?: unknown; weight?: unknown; emphasis?: unknown};
    const type = String(s.type ?? '') as SceneType;
    if (!(SCENE_TYPES as readonly string[]).includes(type)) {
      throw new Error(`storyboard scene ${index + 1} has unknown type: ${String(s.type ?? '')}`);
    }
    if (!s.props || typeof s.props !== 'object') {
      throw new Error(`storyboard scene ${index + 1} props must be an object`);
    }
    const props = s.props as Record<string, unknown>;
    if (!hasRequiredSceneText(type, props)) {
      throw new Error(`storyboard scene ${index + 1} (${type}) missing provider-authored text`);
    }
    const weight = typeof s.weight === 'number' && Number.isFinite(s.weight) && s.weight > 0 ? s.weight : undefined;
    const emphasis =
      s.emphasis === 'low' || s.emphasis === 'high' || s.emphasis === 'normal' ? s.emphasis : undefined;
    scenes.push({type, props, weight, emphasis});
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
  const hasMetricSignal = /\d/.test(data.audienceMetricLine || '');
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
    ...(hasMetricSignal
      ? [
          {
            type: 'chart' as const,
            props: {
              kicker: '数据先当信号看',
              heading: '热度不是结论，但能说明关注方向',
              label: '公开指标',
              value: data.audienceMetricLine,
              points: ['来源', '关注', '判断'],
            },
          },
        ]
      : []),
    ...(data.url.includes('github.com') ? [
      {
        type: 'terminal' as const,
        props: {
          kicker: '开发者会先这样判断',
          title: '最小上手路径',
          prompt: '$',
          lines: ['clone / install', 'run quick start', 'inspect examples', 'check tests'],
        },
      },
      {
        type: 'flow' as const,
        props: {
          kicker: '机制不要只靠文字讲',
          heading: '把 repo 还原成一条工作流',
          nodes: ['输入', '核心模块', '输出', '失败边界'],
          caption: '这类场景让 agent 用结构图解释机制，而不是堆段落。',
        },
      },
      {
        type: 'code_diff' as const,
        props: {
          kicker: '源码视角',
          title: '别只复述 README',
          filename: 'repo / docs / tests',
          additions: ['看入口模块', '看示例输入输出', '看测试和 CI'],
          removals: ['只看 star 数'],
        },
      },
    ] : []),
    ...data.cards.slice(0, data.url.includes('github.com') && hasMetricSignal ? 1 : data.url.includes('github.com') ? 2 : 4).map((card) => ({
      type: 'card' as const,
      props: {label: card.label, value: card.value, detail: card.detail},
    })),
    {
      type: 'cta',
      props: {kicker: '判断框架', text: data.cta, footer: data.verificationNextStep || data.footer},
    },
  ];
  return {version: 1, style: {theme: 'radar'}, scenes};
};

// Engineering-theme factory. Produces an 8-scene storyboard that walks through
// the same content from a technical angle: opener, act cards, code sample,
// agent graph, decision table, and closing wordmark. Mirrors the structure of
// the SightLine demo (act-based engineering reveal). Call this from your content
// agent when the topic has technical depth worth showcasing.
export type EngineeringStoryboardInput = {
  topic: string;
  tagline: string;
  subtitle?: string;
  codeFilename: string;
  codeLines: string[];
  codeCaption: string;
  graphCenter: string;
  graphCenterSub?: string;
  graphNodes: string[];
  graphSubs?: string[];
  rules: string[];
  ruleTags?: string[];
  categories: string[];
  categorySubs?: string[];
  title: string;
  closingMark?: string;
  closingSub?: string;
  closingBuilt?: string;
  actLabels?: {engine?: string; architecture?: string; decision?: string};
  style?: StyleTokens;
};

export const deriveEngineeringStoryboard = (input: EngineeringStoryboardInput): Storyboard => {
  const acts = input.actLabels || {};
  const scenes: Scene[] = [
    // Act 1 opener - the problem statement in the engineering voice.
    {
      type: 'statement',
      props: {
        kicker: input.tagline,
        title: input.topic,
        sub: input.subtitle ?? '',
      },
      weight: 0.16,
    },
    // Act 1 - the engine / code.
    {
      type: 'act_card',
      props: {
        eyebrow: `ACT 1`,
        detail: acts.engine ?? 'The Engine',
        sub: input.codeCaption.slice(0, 90),
      },
      weight: 0.05,
    },
    {
      type: 'code_block',
      props: {
        filename: input.codeFilename,
        lines: input.codeLines,
        title: input.codeCaption,
        detail: input.subtitle ?? '',
      },
      weight: 0.18,
    },
    // Act 2 - the architecture.
    {
      type: 'act_card',
      props: {
        eyebrow: `ACT 2`,
        detail: acts.architecture ?? 'The Architecture',
        sub: '',
      },
      weight: 0.05,
    },
    {
      type: 'node_graph',
      props: {
        center: input.graphCenter,
        centerSub: input.graphCenterSub ?? 'orchestrator',
        nodes: input.graphNodes,
        subs: input.graphSubs ?? [],
        title: '',
      },
      weight: 0.18,
    },
    // Act 3 - the decision / memory.
    {
      type: 'act_card',
      props: {
        eyebrow: `ACT 3`,
        detail: acts.decision ?? 'The Decision',
        sub: '',
      },
      weight: 0.05,
    },
    {
      type: 'decision_table',
      props: {
        title: input.title,
        rules: input.rules,
        tags: input.ruleTags ?? [],
        categories: input.categories,
        categorySubs: input.categorySubs ?? [],
      },
      weight: 0.22,
    },
    // Closing wordmark.
    {
      type: 'closing',
      props: {
        mark: input.closingMark ?? 'searchpo',
        sub: input.closingSub ?? 'engineering videos for AI builders',
        built: input.closingBuilt ?? 'built for the agents that watch the world',
      },
      weight: 0.11,
    },
  ];
  const style: StyleTokens = input.style ?? {theme: 'engineering', motion: 'calm', density: 'minimal'};
  return {version: 1, style, scenes};
};
