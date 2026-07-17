import React from 'react';
import {AbsoluteFill, useCurrentFrame, interpolate} from 'remotion';

export const ScreenShake: React.FC<{children: React.ReactNode; intensity?: number}> = ({children, intensity = 10}) => {
  const frame = useCurrentFrame();
  // We want a high frequency shake
  const offsetX = Math.sin(frame * 0.8) * intensity;
  const offsetY = Math.cos(frame * 0.75) * intensity;

  return (
    <div style={{width: '100%', height: '100%', transform: `translate(${offsetX}px, ${offsetY}px)`}}>
      {children}
    </div>
  );
};

export const GlitchFlash: React.FC<{duration?: number}> = ({duration = 15}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, duration], [0.8, 0], {extrapolateRight: 'clamp'});

  return (
    <AbsoluteFill style={{pointerEvents: 'none', mixBlendMode: 'screen', opacity, zIndex: 9999}}>
      <div style={{
        position: 'absolute', width: '100%', height: '100%',
        background: 'linear-gradient(transparent 50%, rgba(255,0,0,0.2) 50%)',
        backgroundSize: '100% 4px',
        transform: 'translateX(10px)'
      }} />
      <div style={{
        position: 'absolute', width: '100%', height: '100%',
        background: 'linear-gradient(transparent 50%, rgba(0,255,255,0.2) 50%)',
        backgroundSize: '100% 4px',
        transform: 'translateX(-10px)'
      }} />
    </AbsoluteFill>
  );
};

export const HexGrid: React.FC = () => {
  const frame = useCurrentFrame();
  // Pulsing opacity based on sine wave
  const opacity = interpolate(Math.sin(frame * 0.04), [-1, 1], [0.1, 0.3], {extrapolateRight: 'clamp'});

  return (
    <AbsoluteFill style={{pointerEvents: 'none', zIndex: 0}}>
       <div style={{
          width: '100%', height: '100%',
          backgroundImage: `url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="60" height="103.923" viewBox="0 0 60 103.923"><path d="M30 0l25.981 15v30l-25.981 15-25.981-15v-30z" fill="none" stroke="rgba(0,212,255,0.5)" stroke-width="1"/></svg>')`,
          backgroundSize: '60px 103.92px',
          opacity
       }} />
    </AbsoluteFill>
  );
};
