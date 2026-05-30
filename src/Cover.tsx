import {AbsoluteFill} from 'remotion';
import payload from '../public/searchpo-content.json';
import type {Payload} from './Composition';

const samplePayload = payload as Payload;

const coverFor = (props: Partial<Payload>): Payload => ({...samplePayload, ...props});

const clamp = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

// A still composition rendered to a JPG by `remotion still` and used as the
// Douyin video cover. Designed for thumbnail legibility: one giant hook line,
// a high-contrast metric badge, and the source boundary.
export const SearchpoCover: React.FC<Partial<Payload>> = (props) => {
  const data = coverFor(props);
  const metric = data.metricLine || (data.score != null ? `score ${data.score}` : '');
  return (
    <AbsoluteFill className="canvas cover">
      <div className="noise" />
      <div className="beam cover-beam" />

      <div className="cover-top">
        <span className="cover-badge">{data.badge || '今日 AI 工具热点'}</span>
        <span className="cover-mark">searchpo 雷达</span>
      </div>

      <div className="cover-kicker">今天为什么刷到它</div>
      <h1 className="cover-title">{clamp(data.title, 48)}</h1>

      {metric ? <div className="cover-metric">{clamp(metric, 30)}</div> : null}

      <div className="cover-bottom">
        <div className="cover-source">
          <span>来源边界</span>
          <strong>{clamp(data.source, 40)}</strong>
        </div>
        <div className="cover-cta">{audioHint(data)}</div>
      </div>
    </AbsoluteFill>
  );
};

const audioHint = (data: Payload) => clamp(data.cta || '看完再决定要不要追', 16);
