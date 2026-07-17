import {useCurrentFrame, interpolate} from 'remotion';

// Deterministic pseudo-random number generator
export const seededRandom = (seed: number) => {
  const x = Math.sin(seed++) * 10000;
  return x - Math.floor(x);
};

// Continuous pulsing for opacities or blurs
export const useContinuousPulse = (speed = 0.05, min = 0.7, max = 1.0) => {
  const frame = useCurrentFrame();
  return interpolate(Math.sin(frame * speed), [-1, 1], [min, max], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
};

// Continuous floating for vertical translations
export const useFloat = (speed = 0.03, amplitude = 5) => {
  const frame = useCurrentFrame();
  return Math.sin(frame * speed) * amplitude;
};
