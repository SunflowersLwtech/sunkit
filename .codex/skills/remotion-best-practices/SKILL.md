---
name: remotion-best-practices
description: Remotion video composition best practices for searchpo. Use when editing src/ components, configuring rendering, optimizing video output, or adding animations/effects to the Remotion pipeline.
version: 1.1.0
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
- Composition: `SearchpoRadar` — storyboard-driven 1080×1920 vertical video
- Output: Douyin vertical video (9:16)
- Rendering: local (`remotion render`) or Lambda (`@remotion/lambda`)
- Audio source: Gemini 3.1 Flash TTS (`gemini-3.1-flash-tts-preview`) → `voiceover.wav`
- Content: DeepSeek V4 Pro (`deepseek-v4-pro`) polished copy
- Quality gate: `scripts/video_quality_loop.py` wraps Remotion render, metadata checks, deterministic audit, Gemini 3.5 Flash visual audit, automatic layout repair, and final artifact promotion.

## Architecture Rules

### Composition Design

- `src/Composition.tsx` owns the global video shell. Scene-specific blocks live under `src/scenes/`, and storyboard contract/timing helpers live in `src/storyboard.ts`.
- Props are typed via `Payload` interface. Data comes from `remotion_input_props.json` at render time and should include a validated `storyboard`; `video_spec.json` is the renderer-neutral planning artifact compiled into `render_payload.json`, and legacy `cards` are only a compatibility fallback.
- The storyboard scene types are `statement`, `context`, `stat`, `bullets`, `card`, `compare`, `quote`, and `cta`. Keep each block inside the visual safe band above the bottom caption area.
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
