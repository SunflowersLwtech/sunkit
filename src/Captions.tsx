import {useMemo} from 'react';
import {interpolate, useCurrentFrame} from 'remotion';

export type CaptionSegment = {
  text: string;
  startFrame: number;
  endFrame: number;
};

type CaptionsProps = {
  segments: CaptionSegment[];
};

export const Captions: React.FC<CaptionsProps> = ({segments}) => {
  const frame = useCurrentFrame();

  const active: CaptionSegment[] = useMemo(() => {
    if (!segments || segments.length === 0) {
      throw new Error('Captions requires timed segments from scripts/build_captions.py.');
    }
    return segments;
  }, [segments]);


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
      <svg className="caption-svg-defs" aria-hidden="true" focusable="false">
        <filter id="caption-stroke" colorInterpolationFilters="sRGB">
          <feMorphology in="SourceAlpha" operator="dilate" radius="2.8" result="stroke" />
          <feGaussianBlur in="stroke" stdDeviation="0.65" result="softStroke" />
          <feFlood floodColor="rgba(0, 0, 0, 0.92)" result="strokeColor" />
          <feComposite in="strokeColor" in2="softStroke" operator="in" result="coloredStroke" />
          <feMerge>
            <feMergeNode in="coloredStroke" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </svg>
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
