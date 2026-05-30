import './styles.css';
import {Composition} from 'remotion';
import samplePayload from '../public/searchpo-content.json';
import {type Payload, SearchpoRadar} from './Composition';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="SearchpoRadar"
      component={SearchpoRadar}
      calculateMetadata={({props}) => ({
        durationInFrames: (props as any).durationInFrames || 360,
        fps: 30,
        width: 1080,
        height: 1920,
      })}
      durationInFrames={360}
      fps={30}
      width={1080}
      height={1920}
      defaultProps={samplePayload as Payload}
    />
  );
};
