import type {ReactNode} from 'react';
import type {Payload} from './Composition';

export type AgentVisualProps = {
  data: Payload;
  frame: number;
  fps: number;
  durationInFrames: number;
  width: number;
  height: number;
  progress: number;
  audioPulse: number;
  captions?: ReactNode;
};
