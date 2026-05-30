import {AbsoluteFill} from 'remotion';
import {assertPayload, type Payload} from './Composition';

const clamp = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

const titleForCover = (text: string) => {
  const title = clamp(text, 48);
  const slashIndex = title.indexOf('/');
  if (slashIndex > 0 && slashIndex < title.length - 1) {
    return (
      <>
        {title.slice(0, slashIndex + 1)}
        <br />
        {title.slice(slashIndex + 1)}
      </>
    );
  }
  return title;
};

const requireText = (value: string, field: string): string => {
  if (!value || !value.trim()) {
    throw new Error(`SearchpoCover missing required prop: ${field}`);
  }
  return value;
};

// A still composition rendered to a JPG by `remotion still` and used as the
// Douyin video cover. Designed for thumbnail legibility: one giant hook line,
// a high-contrast metric badge, and the source boundary.
export const SearchpoCover: React.FC<Partial<Payload>> = (props) => {
  const data = assertPayload(props);
  const metric = requireText(data.metricLine, 'metricLine');
  return (
    <AbsoluteFill className="canvas cover">
      <div className="noise" />
      <div className="beam cover-beam" />

      <div className="cover-top">
        <span className="cover-badge">{requireText(data.badge, 'badge')}</span>
        <span className="cover-mark">searchpo 雷达</span>
      </div>

      <div className="cover-kicker">今天为什么刷到它</div>
      <h1 className="cover-title">{titleForCover(requireText(data.title, 'title'))}</h1>

      <div className="cover-metric">{clamp(metric, 30)}</div>

      <div className="cover-bottom">
        <div className="cover-source">
          <span>来源边界</span>
          <strong>{clamp(requireText(data.source, 'source'), 40)}</strong>
        </div>
        <div className="cover-cta">{audioHint(data)}</div>
      </div>
    </AbsoluteFill>
  );
};

const audioHint = (data: Payload) => clamp(requireText(data.cta, 'cta'), 16);
