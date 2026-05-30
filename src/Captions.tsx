import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

type CaptionsProps = {
  text: string;
  startFrame?: number;
  durationFrames?: number;
};

const CHARS_PER_GROUP = 8;

export const Captions: React.FC<CaptionsProps> = ({text, startFrame = 20, durationFrames}) => {
  const frame = useCurrentFrame();
  const {durationInFrames, fps} = useVideoConfig();
  const totalDuration = durationFrames || durationInFrames - startFrame - 30;
  const relativeFrame = frame - startFrame;

  if (relativeFrame < 0 || !text) return null;

  const groups: string[] = [];
  for (let i = 0; i < text.length; i += CHARS_PER_GROUP) {
    groups.push(text.slice(i, i + CHARS_PER_GROUP));
  }

  const framesPerGroup = totalDuration / groups.length;
  const currentGroupIndex = Math.min(
    Math.floor(relativeFrame / framesPerGroup),
    groups.length - 1,
  );

  const windowStart = Math.max(0, currentGroupIndex - 1);
  const windowEnd = Math.min(groups.length, currentGroupIndex + 3);
  const visibleGroups = groups.slice(windowStart, windowEnd);

  return (
    <div className="captions-container">
      <div className="captions-track">
        {visibleGroups.map((group, i) => {
          const globalIndex = windowStart + i;
          const isActive = globalIndex === currentGroupIndex;
          const groupProgress = (relativeFrame - globalIndex * framesPerGroup) / framesPerGroup;
          const opacity = isActive ? 1 : interpolate(
            Math.abs(globalIndex - currentGroupIndex),
            [0, 1, 2],
            [1, 0.5, 0.25],
          );

          return (
            <span
              key={globalIndex}
              className={`caption-word${isActive ? ' caption-active' : ''}`}
              style={{opacity}}
            >
              {group}
            </span>
          );
        })}
      </div>
    </div>
  );
};
