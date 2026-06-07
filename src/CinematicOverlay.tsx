import {AbsoluteFill} from 'remotion';
import React from 'react';

export const CinematicOverlay: React.FC = () => {
  return (
    <AbsoluteFill
      style={{
        pointerEvents: 'none',
        zIndex: 2,
        mixBlendMode: 'overlay',
      }}
    >
      <div
        style={{
          width: '100%',
          height: '100%',
          background: `radial-gradient(circle, transparent 50%, rgba(0,0,0,0.6) 130%)`,
          position: 'absolute',
        }}
      />
      <svg
        style={{
          width: '100%',
          height: '100%',
          opacity: 0.35,
        }}
      >
        <filter id="noiseFilter">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.75"
            numOctaves="3"
            stitchTiles="stitch"
          />
        </filter>
        <rect width="100%" height="100%" filter="url(#noiseFilter)" />
      </svg>
    </AbsoluteFill>
  );
};
