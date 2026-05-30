import './styles.css';
import {Composition, Still} from 'remotion';
import samplePayload from '../public/searchpo-content.json';
import {type Payload, SearchpoRadar} from './Composition';
import {SearchpoCover} from './Cover';

const sample = samplePayload as Payload;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="SearchpoRadar"
        component={SearchpoRadar}
        calculateMetadata={({props}) => {
          const p = props as Payload;
          return {
            // Duration follows the real audio length (set by the pipeline);
            // falls back to 360 frames (12s) for no-audio / contract runs.
            durationInFrames: Math.max(60, Math.round(p.durationInFrames || 360)),
            fps: p.fps || 30,
            width: 1080,
            height: 1920,
          };
        }}
        durationInFrames={360}
        fps={30}
        width={1080}
        height={1920}
        defaultProps={sample}
      />
      <Still
        id="SearchpoCover"
        component={SearchpoCover}
        width={1080}
        height={1920}
        defaultProps={sample}
      />
    </>
  );
};
