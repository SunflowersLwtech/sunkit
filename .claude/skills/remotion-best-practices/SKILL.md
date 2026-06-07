---
name: remotion-best-practices
description: Remotion video composition best practices for searchpo. Use when editing src/ components, configuring rendering, optimizing video output, or adding animations/effects to the Remotion pipeline.
version: 1.2.0
triggers:
  - "Remotion"
  - "src/Composition"
  - "captions"
  - "cover"
  - "render metadata"
  - "Lambda render"
  - "video output"
  - "animation"
  - "Douyin video"
tools:
  - shell
  - filesystem
mutating: true
applies_to:
  - "src/"
  - "render/"
  - "scripts/remotion_render.sh"
  - "scripts/lambda_render.sh"
---

# Remotion Best Practices for Searchpo

## Project Context

- Remotion 4.0.468 (React 19)
- Composition: `SearchpoRadar` — storyboard-driven video, vertical 1080×1920 or horizontal 1920×1080
- Output: Douyin-compatible vertical video (9:16) or horizontal video (16:9), chosen by topic fit
- Rendering: local (`remotion render`) or Lambda (`@remotion/lambda`)
- Audio source: Gemini 3.1 Flash TTS (`gemini-3.1-flash-tts-preview`) → `voiceover.wav`
- Content: DeepSeek V4 Pro (`deepseek-v4-pro`) polished copy
- Quality gate: `scripts/video_quality_loop.py` wraps Remotion render, metadata checks, deterministic audit, Gemini 3.5 Flash visual audit, automatic layout repair, and final artifact promotion.

## Architecture Rules

### Composition Design

- `src/Composition.tsx` owns the global video shell. Scene-specific blocks live under `src/scenes/`, and storyboard contract/timing helpers live in `src/storyboard.ts`.
- Props are typed via `Payload` interface. Data comes from `remotion_input_props.json` at render time and should include a validated `storyboard`; `video_spec.json` is the renderer-neutral planning artifact compiled into `render_payload.json`, and legacy `cards` are only a compatibility fallback.
- The storyboard scene types are `statement`, `context`, `stat`, `bullets`, `card`, `compare`, `compare_table`, `terminal`, `flow`, `chart`, `code_diff`, `quote`, and `cta`. Keep each block inside the visual safe band above the bottom caption area.
- Do not force every provider run into short vertical format. For code, architecture, wide timelines, comparison tables, and dense technical explainers, horizontal `16:9` is valid when `videoProfile.orientation`, `aspectRatio`, width, height, Remotion metadata, and deterministic audit all agree.
- Style variation is limited to brand-safe tokens: `theme`, `density`, `motion`, `accent`, and `chrome` toggles. Do not let provider output inject arbitrary CSS or remote assets.
- Use `useCurrentFrame()` + `useVideoConfig()` as the timing source. Never use `setTimeout` or CSS animations.
- Use `interpolate()` for linear/eased transitions. Use `spring()` for physics-based motion.
- Render scene lists with `@remotion/transitions` `TransitionSeries` when `chooseTransitionFrames()` can preserve readable dwell time and keep the midpoint OCR sample out of a cross-fade; otherwise fall back to plain `Series`.

### Animation Patterns

```tsx
// Frame-based interpolation (preferred for predictable timing)
const opacity = interpolate(frame, [0, 30], [0, 1], {extrapolateRight: 'clamp'});

// Spring for natural entrance (cards, titles)
const enter = spring({frame: frame - delay, fps, config: {damping: 18, stiffness: 110}});

// Looping animation (pulse, glow)
const pulse = interpolate(Math.sin(frame / 10), [-1, 1], [0.4, 1]);

// Stagger children
const stagger = (index: number, base: number, gap: number) =>
  spring({frame: frame - base - index * gap, fps, config: {damping: 18, stiffness: 110}});
```

### Writing Richly Animated `agent_visual` TSX Components

Provider videos must use a custom, topic-specific `agent_visual`; storyboard scenes and legacy `cards` are compatibility data, not the main provider visual surface. Aggressive visual generation is enabled:

- Prefer `agent_visual.module_code`: a complete TSX module written to `src/generated/AgentVisual.generated.tsx`. It must export a named `AgentVisualGenerated` component and may import React, Remotion APIs, installed `@remotion/*` packages, and local helpers under `src/components` or `src/utils`.
- Keep `agent_visual.component_code` only as a compatibility path: it is a TSX function body inserted inside `AgentVisualGenerated` and receives the provided runtime values `data`, `frame`, `fps`, `durationInFrames`, `width`, `height`, `progress`, `audioPulse`, `React`, `AbsoluteFill`, `interpolate`, `spring`, `useMemo`, `Img`, `staticFile`, `Series`, and `Sequence`.
- Do not use local filesystem/process/env access, persistent browser storage, cookies, or code that can leak `.env` values.

Hard visual contract:

- Do not render captions, subtitles, or a second bottom text overlay; global captions are already applied.
- Do not use `data.cards`, `safeCards`, full `data.summary`, `data.evidenceLevel`, source paths, or operator/internal metadata as the main visual.
- Do not use CSS `animation` or `transition`; every movement must be frame-driven from `frame`, `progress`, `audioPulse`, `interpolate()`, `spring()`, or `Math.sin(frame / N)`.
- Absolute positioning, SVG coordinates, paths, masks, clip paths, transforms, and layered overlays are allowed when they improve the composition. For vertical Douyin output keep the important visual content clear of the bottom caption band, roughly `560px`; for horizontal output reserve roughly `180px`.
- Keep the full-canvas background above near-black luma; pure black frames can fail deterministic audit.

Deterministic motion target:

- Central content must move in the first 8 seconds. This is the authoring target even when the current audit samples a shorter opening window for short videos.
- Central content must not remain static for more than 10 seconds.
- Aim well above the audit minimum: `motion_check.active_pair_ratio >= 0.20` and at least 4 active pairs.
- Captions, progress bars, text highlights, fades, and chrome-only movement do not count as enough central motion.
- Build at least four motion layers: spring entrance, staggered child reveals, continuous central idle movement, and audio-reactive emphasis.
- Let the content model choose duration from topic depth and visual plan. `180s+` is not a default target; it is the long-form quality threshold. If the model chooses 180 seconds or longer, author a chaptered visual plan with at least 9 storyboard scenes and enough `agent_visual` states to sustain the entire narration. A short 3-7 scene storyboard stretched over 3+ minutes is a quality failure.

Topic-specific visual recipes:

- Software or repo topics: terminal, code panel, diff, file tree, docs/browser pane, architecture flow, or verification path.
- Metric-heavy topics: animated chart, bars, matrix, timeline, or score dial instead of static numbers.
- Tradeoff topics: compare table, decision matrix, suitable/not-suitable split, or before/after panels.
- Process topics: timeline, node graph, pipeline, queue, or system map.

Copy-paste body template for `agent_visual.component_code`:

```tsx
const isVertical = height >= width;
const bottomSafe = isVertical ? 560 : 180;
const sidePad = isVertical ? 72 : 104;
const title = String(data.displayTitle || data.title || 'Searchpo signal').slice(0, 46);
const source = String(data.source || 'verified source').slice(0, 34);

const beats = useMemo(() => {
  const scenes = Array.isArray(data.storyboard?.scenes) ? data.storyboard.scenes : [];
  const mapped = scenes.slice(0, 4).map((scene, index) => {
    const props = scene?.props || {};
    return {
      label: String(props.title || props.heading || props.label || scene.type || `Step ${index + 1}`).slice(0, 24),
      detail: String(props.detail || props.text || props.summary || props.value || '').slice(0, 44),
    };
  });
  return mapped.length > 0
    ? mapped
    : [
        {label: 'Problem', detail: 'What changed'},
        {label: 'Mechanism', detail: 'How it works'},
        {label: 'Boundary', detail: 'What to verify'},
      ];
}, [data.storyboard]);

const entrance = spring({frame, fps, config: {damping: 18, stiffness: 120}});
const breathing = interpolate(Math.sin(frame / 16), [-1, 1], [0.985, 1.025]);
const floatY = interpolate(Math.sin(frame / 22), [-1, 1], [-16, 16]);
const orbit = interpolate(Math.sin(frame / 29), [-1, 1], [-22, 22]);
const scan = interpolate((frame % Math.max(1, durationInFrames)) / Math.max(1, durationInFrames), [0, 1], [-18, 118]);
const audioScale = interpolate(audioPulse, [0, 1], [1, 1.055], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

return (
  <AbsoluteFill
    style={{
      background: 'linear-gradient(135deg, #182433 0%, #263449 48%, #fff7df 100%)',
      color: '#fffdf4',
      padding: `72px ${sidePad}px ${bottomSafe}px`,
      overflow: 'hidden',
    }}
  >
    <div style={{height: '100%', display: 'grid', gridTemplateRows: 'auto minmax(0, 1fr)', gap: 34}}>
      <div style={{opacity: entrance, transform: `translateY(${(1 - entrance) * -28}px)`}}>
        <div style={{fontSize: 26, letterSpacing: 0, color: '#72e7ff'}}>{source}</div>
        <div style={{fontSize: isVertical ? 58 : 48, fontWeight: 800, lineHeight: 1.04, marginTop: 12}}>{title}</div>
      </div>

      <div
        style={{
          minHeight: 0,
          display: 'grid',
          gridTemplateColumns: isVertical ? '1fr' : '1.05fr 0.95fr',
          alignItems: 'center',
          gap: 28,
          transform: `scale(${breathing * audioScale}) translateY(${floatY}px)`,
        }}
      >
        <div
          style={{
            minHeight: isVertical ? 520 : 420,
            borderRadius: 28,
            padding: 28,
            background: `linear-gradient(90deg, rgba(13, 25, 40, 0.72) 0%, rgba(13, 25, 40, 0.72) ${scan - 12}%, rgba(255, 214, 10, 0.20) ${scan}%, rgba(13, 25, 40, 0.72) ${scan + 12}%)`,
            border: '2px solid rgba(114, 231, 255, 0.36)',
            boxShadow: '0 34px 90px rgba(5, 13, 24, 0.32)',
            overflow: 'hidden',
          }}
        >
          <div style={{display: 'grid', gap: 18}}>
            {beats.map((beat, index) => {
              const itemEnter = spring({frame: frame - 8 - index * 9, fps, config: {damping: 17, stiffness: 115}});
              const active = Math.sin((frame + index * 13) / 18);
              return (
                <div
                  key={beat.label}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '54px 1fr',
                    gap: 18,
                    alignItems: 'center',
                    opacity: itemEnter,
                    transform: `translateX(${(1 - itemEnter) * 46 + active * 5}px)`,
                  }}
                >
                  <div
                    style={{
                      width: 54,
                      height: 54,
                      borderRadius: 18,
                      display: 'grid',
                      placeItems: 'center',
                      background: index % 2 === 0 ? '#ffd60a' : '#72e7ff',
                      color: '#162232',
                      fontSize: 24,
                      fontWeight: 900,
                    }}
                  >
                    {index + 1}
                  </div>
                  <div>
                    <div style={{fontSize: 30, fontWeight: 800, lineHeight: 1.05}}>{beat.label}</div>
                    <div style={{fontSize: 21, color: 'rgba(255, 253, 244, 0.74)', marginTop: 6}}>{beat.detail}</div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div
          style={{
            minHeight: isVertical ? 260 : 420,
            display: 'grid',
            placeItems: 'center',
            transform: `translateX(${orbit}px)`,
          }}
        >
          <div
            style={{
              width: isVertical ? 300 : 360,
              height: isVertical ? 300 : 360,
              borderRadius: 44,
              display: 'grid',
              placeItems: 'center',
              background: 'radial-gradient(circle, #ffd60a 0%, #ff2d55 54%, rgba(255, 45, 85, 0.18) 70%)',
              color: '#111827',
              fontSize: 86,
              fontWeight: 900,
              transform: `rotate(${Math.sin(frame / 34) * 4}deg)`,
              boxShadow: '0 26px 80px rgba(255, 45, 85, 0.32)',
            }}
          >
            {Math.round(progress * 100)}
          </div>
        </div>
      </div>
    </div>
  </AbsoluteFill>
);
```

Use the template as a structural starting point, then replace the central primitives with source-grounded visuals for the actual topic. For example, swap the numbered beat list for a terminal command stream, code diff, architecture nodes, chart bars, or matrix cells, but keep the same continuous motion layers and safe-area padding.

### Performance

- Minimize DOM nodes. Remotion renders every frame as a screenshot — heavy DOM = slow render.
- Avoid re-creating large objects per frame. Use `useMemo()` for parsed data.
- Use `staticFile()` for assets in `public/`. Never use external URLs (they break in Lambda).
- Images: prefer PNG/SVG over JPEG for crisp rendering at 1080p.
- Audio: embed via `<Audio src={staticFile(path)} />`. Remotion handles sync automatically.

### Rendering Quality

```bash
# High-quality local render (CRF 18 = visually lossless H.264)
remotion render SearchpoRadar out/video.mp4 \
  --props props.json \
  --codec=h264 \
  --pixel-format=yuv420p \
  --crf=18 \
  --audio-bitrate=192K

# Even higher quality (slower encode, better for archival)
--crf=15 --preset=slow
```

- `--crf 18` is the sweet spot for Douyin (high quality, reasonable file size ~5-8MB for 12s).
- `--pixel-format=yuv420p` is required for cross-device compatibility.
- For Lambda: same codec flags apply via `renderMediaOnLambda()` options.
- In Searchpo Lambda mode, render with `REMOTION_LAMBDA_PRIVACY=private`, pass `REMOTION_LAMBDA_DELETE_AFTER` to both video and cover still commands, and default to `REMOTION_LAMBDA_CONCURRENCY=4`. Only set `SEARCHPO_LAMBDA_FRAMES_PER_LAMBDA` when explicitly choosing frame-count partitioning.

### Captioning / Subtitles

- Use `@remotion/captions` package or custom `<Captions>` component (we use custom in `src/Captions.tsx`).
- Captions should be positioned in the "safe zone" (bottom 15-25% of frame, avoid Douyin UI overlay).
- Use contrasting background (semi-transparent dark) for readability on any background.
- Highlight active word/group with accent color for engagement (yellow #ffd60a in our palette).

### Audio Handling

- Voiceover WAV goes to `public/generated/voiceover.wav` before render.
- `<Audio>` component auto-syncs with frame timeline.
- Audio duration should match composition duration (360 frames / 30fps = 12s). If shorter, Remotion pads silence. If longer, it clips.
- Always normalize audio to -16 LUFS before rendering (`scripts/normalize_audio.sh`).

### Transitions

```tsx
// Fade in/out for intro/outro (critical for Douyin — no hard cuts)
const introOpacity = interpolate(frame, [0, 18], [0, 1], {extrapolateRight: 'clamp'});
const outroOpacity = interpolate(frame, [durationInFrames - 30, durationInFrames - 6], [1, 0], {extrapolateLeft: 'clamp'});

// Slide transition
const slideX = interpolate(frame, [startFrame, startFrame + 20], [1080, 0], {extrapolateRight: 'clamp'});
```

Storyboard timing rule:

- Let `N = scenes.length` and `T = transitionFrames`.
- Compute scene durations against `durationInFrames + (N - 1) * T`.
- `TransitionSeries` consumes `sum(sceneDurations) - (N - 1) * T`, so the final timeline still equals the real audio/caption duration.
- The first and last `TransitionSeries` children must be `Sequence`, not `Transition`.

### Common Pitfalls

| Mistake | Fix |
|---------|-----|
| Using `window.setTimeout` | Use frame-based logic: `if (frame > N)` |
| Fetching remote data in component | Pre-compute in `prepare_remotion_input.py`, pass via props |
| CSS `transition` / `animation` | Use Remotion `interpolate()` / `spring()` |
| Font not rendering | Use offline fontsource CSS imports in `src/fonts.ts` and gate on `document.fonts.ready` |
| Audio out of sync | Check audio sample rate matches (24kHz WAV), normalize before render |
| Black frames at start | Add intro fade: `interpolate(frame, [0, N], [0, 1])` |
| Lambda timeout | Increase `REMOTION_LAMBDA_TIMEOUT_SEC` or reduce composition complexity |
| Flickering text | Avoid conditional rendering mid-frame; use opacity instead |

### File Layout

```
src/
├── index.ts           # registerRoot
├── Root.tsx           # <Composition> registration (specs, defaultProps)
├── Composition.tsx    # Main storyboard shell (SearchpoRadar)
├── storyboard.ts      # Storyboard contract, timing, style tokens
├── scenes/            # Vetted scene block components
├── Captions.tsx       # Dynamic subtitle overlay
└── styles.css         # All styling (no CSS modules, no Tailwind)

public/
├── searchpo-content.json    # Sample/dev props fixture
└── generated/
    └── voiceover.wav        # Runtime audio (copied by prepare_remotion_input.py)

render/
└── prepare_remotion_input.py  # Transforms video_spec/render_payload run artifacts → Remotion props JSON

scripts/
├── remotion_render.sh         # Local render wrapper (--crf, --audio-bitrate)
└── lambda_render.sh           # Lambda site upload + render
```

### Douyin-Specific Requirements

- Aspect ratio: 9:16 (1080×1920). Never crop to 16:9.
- First 2 seconds must have visual movement (hook). Douyin algorithm penalizes static openings.
- Text must be readable at phone distance (minimum 24px at 1080w = effectively 34px in our layout).
- Avoid solid white backgrounds (overexposure on OLED phones).
- Include captions — Douyin shows 40%+ completion rate boost with subtitles.
- Keep total duration 8-15s for optimal algorithmic distribution.

### Adding New Visual Elements

1. Decide whether the element is a new scene type or belongs inside an existing scene block.
2. Add the scene props bounds to `src/storyboard.ts` and `agent_harness/storyboard.py`.
3. Add or update the block under `src/scenes/` with frame-based timing and safe-area constraints.
4. Style in `styles.css` using stable dimensions; avoid text overflow and arbitrary provider-controlled CSS.
5. Update `contracts/schemas/render_payload.schema.json`, DeepSeek policy, and tests when the storyboard contract changes.
6. Test in Remotion Studio: `npm run dev` → preview at http://localhost:3000.
7. Verify with the video quality loop rather than manually binding failed previews: `python3 scripts/video_quality_loop.py "$(cat runtime/latest_run.txt)" --execution-profile provider --render-mode local --publish-mode contract-check`.
