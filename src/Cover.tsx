import {AbsoluteFill} from 'remotion';
import {assertPayload, type Payload} from './Composition';
import {useFontsReady} from './fonts';

const clamp = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

const cjk = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]/;
const closingPunctuation = new Set(Array.from('/|,，;；。.!?！？:：)]}）】》”’、'));
const openingPunctuation = new Set(Array.from('([{（【《“‘'));

const charWeight = (ch: string) => {
  if (cjk.test(ch)) return 1;
  if (/^[A-Za-z0-9]$/.test(ch)) return 0.58;
  if (/\s/.test(ch)) return 0.28;
  return 0.45;
};

const lineWeight = (line: string) => Array.from(line).reduce((sum, ch) => sum + charWeight(ch), 0);

export const tokenizeTitle = (text: string) => {
  const tokens: string[] = [];
  let buf = '';
  const flush = () => {
    if (buf) tokens.push(buf);
    buf = '';
  };
  for (const ch of Array.from(text)) {
    if (cjk.test(ch)) {
      flush();
      tokens.push(ch);
    } else if (/\s/.test(ch)) {
      flush();
      tokens.push(' ');
    } else if ('/|:：,，;；。!?！？'.includes(ch)) {
      flush();
      tokens.push(ch);
    } else {
      buf += ch;
    }
  }
  flush();
  return tokens;
};

const rebalancePunctuation = (lines: string[]): string[] => {
  const balanced: string[] = [];
  for (const raw of lines) {
    let line = raw.trim();
    if (!line) continue;
    while (line && closingPunctuation.has(Array.from(line)[0]) && balanced.length > 0) {
      const chars = Array.from(line);
      balanced[balanced.length - 1] += chars[0];
      line = chars.slice(1).join('').trimStart();
    }
    if (line) balanced.push(line);
  }
  for (let i = 0; i < balanced.length - 1; i++) {
    const chars = Array.from(balanced[i]);
    const last = chars[chars.length - 1];
    if (last && openingPunctuation.has(last)) {
      balanced[i] = chars.slice(0, -1).join('').trimEnd();
      balanced[i + 1] = `${last}${balanced[i + 1]}`;
    }
  }
  return balanced.filter(Boolean);
};

export const coverTitlePlan = (text: string) => {
  const title = clamp(text.replace(/([A-Za-z0-9_.-]{2,})\/([A-Za-z0-9_.-]{2,})/g, '$1 / $2'), 64);
  const lines: string[] = [];
  let line = '';
  const push = () => {
    const clean = line.trim();
    if (clean) lines.push(clean);
    line = '';
  };
  for (const token of tokenizeTitle(title)) {
    const candidate = `${line}${token}`;
    if (line && token !== ' ' && lineWeight(candidate) > 8.6 && !closingPunctuation.has(token)) {
      push();
    }
    line += token;
  }
  push();
  const balancedLines = rebalancePunctuation(lines);
  const safeLines = (balancedLines.length ? balancedLines : [title]).slice(0, 6);
  const maxWeight = Math.max(...safeLines.map(lineWeight), 1);
  const fontSize = Math.max(64, Math.min(124, Math.floor(930 / maxWeight)));
  return {lines: safeLines, fontSize};
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
  useFontsReady();
  const data = assertPayload(props);
  const metric = requireText(data.audienceMetricLine || data.metricLine, 'audienceMetricLine');
  const titlePlan = coverTitlePlan(requireText(data.displayTitle || data.title, 'displayTitle'));
  return (
    <AbsoluteFill className={`canvas cover aspect-${data.orientation}`}>
      <div className="noise" />
      <div className="beam cover-beam" />

      <div className="cover-top">
        <span className="cover-badge">{requireText(data.badge, 'badge')}</span>
        <span className="cover-mark">searchpo 雷达</span>
      </div>

      <div className="cover-kicker">今天为什么刷到它</div>
      <h1 className="cover-title" style={{fontSize: titlePlan.fontSize}}>
        {titlePlan.lines.map((line, index) => (
          <span className="cover-title-line" key={`${line}-${index}`}>
            {line}
          </span>
        ))}
      </h1>

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
