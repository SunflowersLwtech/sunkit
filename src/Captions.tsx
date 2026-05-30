import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

export type CaptionSegment = {
  text: string;
  startFrame: number;
  endFrame: number;
};

type CaptionsProps = {
  // Frame-accurate segments produced by scripts/build_captions.py from the real
  // audio length. When present these are rendered verbatim (the correct path).
  segments?: CaptionSegment[];
  // Degraded fallback when timing is unavailable (e.g. no audio): even split.
  text?: string;
  startFrame?: number;
};

const FALLBACK_CHARS_PER_GROUP = 9;

// Build evenly-spaced segments only when real timing is missing. This keeps a
// readable caption in contract/no-audio runs without pretending to be in sync.
const fallbackSegments = (text: string, startFrame: number, total: number): CaptionSegment[] => {
  const groups: string[] = [];
  for (let i = 0; i < text.length; i += FALLBACK_CHARS_PER_GROUP) {
    groups.push(text.slice(i, i + FALLBACK_CHARS_PER_GROUP));
  }
  if (groups.length === 0) return [];
  const span = Math.max(groups.length, total - startFrame);
  const per = span / groups.length;
  return groups.map((g, i) => ({
    text: g,
    startFrame: Math.round(startFrame + i * per),
    endFrame: Math.round(startFrame + (i + 1) * per),
  }));
};

export const Captions: React.FC<CaptionsProps> = ({segments, text, startFrame = 8}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();

  const active: CaptionSegment[] =
    segments && segments.length > 0
      ? segments
      : text
      ? fallbackSegments(text, startFrame, durationInFrames - 24)
      : [];

  if (active.length === 0) return null;

  const current = active.find((s) => frame >= s.startFrame && frame < s.endFrame);
  if (!current) return null;

  const span = Math.max(1, current.endFrame - current.startFrame);
  const progress = Math.min(1, Math.max(0, (frame - current.startFrame) / span));
  // Karaoke fill: characters light up as the segment plays, communicating sync.
  const chars = Array.from(current.text);
  const litUpTo = progress * chars.length;
  const enter = interpolate(frame - current.startFrame, [0, 6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <div className="captions-container" style={{opacity: enter}}>
      <div
        className="captions-track"
        style={{transform: `translateY(${interpolate(enter, [0, 1], [12, 0])}px)`}}
      >
        {chars.map((ch, i) => {
          const lit = i < litUpTo;
          return (
            <span key={i} className={`caption-char${lit ? ' caption-lit' : ''}`}>
              {ch === ' ' ? ' ' : ch}
            </span>
          );
        })}
      </div>
    </div>
  );
};
