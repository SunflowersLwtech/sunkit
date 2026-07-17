import {useEffect, useState} from 'react';
import {continueRender, delayRender} from 'remotion';

// Self-hosted brand fonts. The fontsource CSS declares @font-face rules whose
// woff2 files are bundled by Remotion's webpack from node_modules — so they ship
// inside the Studio bundle AND the Lambda site, with NO Google CDN fetch at
// render time (Lambda has no network). Noto Sans SC ships as unicode-range
// subsets for full CJK coverage; the browser only fetches the subsets the
// rendered text actually needs.
import '@fontsource/noto-sans-sc/700.css';
import '@fontsource/noto-sans-sc/900.css';
import '@fontsource/inter/latin-700.css';
import '@fontsource/inter/latin-900.css';

// Latin/digits resolve to Inter; CJK falls through to Noto Sans SC (Inter has no
// CJK glyphs). The trailing system fonts are a last-ditch fallback only.
export const FONT_FAMILY =
  '"Inter", "Noto Sans SC", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", ui-sans-serif, system-ui, sans-serif';

// Block frame capture until the @font-face subsets the rendered text needs are
// ready, so we never screenshot a flash-of-fallback and local renders match
// Lambda byte-for-byte. Used by every registered composition/still.
export const useFontsReady = (): void => {
  const [handle] = useState(() => delayRender('waiting-for-fonts'));
  useEffect(() => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      continueRender(handle);
    };
    document.fonts.ready.then(finish, finish);
    // Safety net so a missing/blocked font can never hang the render.
    const timeout = setTimeout(finish, 10000);
    return () => {
      clearTimeout(timeout);
      finish();
    };
  }, [handle]);
};
