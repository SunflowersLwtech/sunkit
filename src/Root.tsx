import './styles.css';
import './fonts';
import {Composition, Still} from 'remotion';
import {type Payload, SearchpoRadar} from './Composition';
import {SearchpoCover} from './Cover';

const requireFrameCount = (props: Partial<Payload>): number => {
  const duration = props.durationInFrames;
  if (!Number.isFinite(duration) || !duration || duration < 60) {
    throw new Error('SearchpoRadar requires props.durationInFrames >= 60. Run render/prepare_remotion_input.py first.');
  }
  return Math.round(duration);
};

const requireFps = (props: Partial<Payload>): number => {
  const fps = props.fps;
  if (!Number.isFinite(fps) || !fps || fps < 1) {
    throw new Error('SearchpoRadar requires props.fps. Run render/prepare_remotion_input.py first.');
  }
  return Math.round(fps);
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="SearchpoRadar"
        component={SearchpoRadar}
        calculateMetadata={({props}) => {
          return {
            durationInFrames: requireFrameCount(props as Partial<Payload>),
            fps: requireFps(props as Partial<Payload>),
            width: 1080,
            height: 1920,
          };
        }}
        durationInFrames={360}
        fps={30}
        width={1080}
        height={1920}
      />
      <Still
        id="SearchpoCover"
        component={SearchpoCover}
        width={1080}
        height={1920}
      />
    </>
  );
};
