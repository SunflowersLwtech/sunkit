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
  const enter = interpolate(frame - current.startFrame, [0, 6], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const words = current.text.split(/(\s+)/);
  let charAccumulator = 0;

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
        {words.map((word, i) => {
          const wordStartFrac = charAccumulator / current.text.length;
          const wordEndFrac = (charAccumulator + word.length) / current.text.length;
          charAccumulator += word.length;

          const wordProgress = Math.min(1, Math.max(0, (progress - wordStartFrac) / (wordEndFrac - wordStartFrac + 0.01)));
          const wordOpacity = interpolate(wordProgress, [0, 1], [0.4, 1], {extrapolateRight: 'clamp'});
          const wordY = interpolate(wordProgress, [0, 1], [6, 0], {extrapolateRight: 'clamp'});
          const isLit = wordProgress > 0.5;

          return (
            <span
              key={i}
              className={`caption-word${isLit ? ' caption-lit' : ''}`}
              style={{
                opacity: wordOpacity,
                display: 'inline-block',
                transform: `translateY(${wordY}px)`,
                whiteSpace: 'pre'
              }}
            >
              {word === ' ' ? ' ' : word}
            </span>
          );
        })}
      </div>
    </div>
  );
};
