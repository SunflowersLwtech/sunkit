import './styles.css';
import {Composition} from 'remotion';
import {SearchpoRadar} from './Composition';

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="SearchpoRadar"
      component={SearchpoRadar}
      durationInFrames={360}
      fps={30}
      width={1080}
      height={1920}
    />
  );
};
