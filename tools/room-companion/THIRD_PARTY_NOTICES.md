# Third-party notices

## RB14/dji-vcam (MIT)

`room_companion/camera/duml.py` adapts the DUML frame codec of `tools/duml.py` in
<https://github.com/RB14/dji-vcam>, and the command bytes used by the `dji-duml` driver follow that
project's `docs/protocol-notes.md` and `docs/camera-controls.md`.

```
MIT License

Copyright (c) 2026 razboy

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## DJI R SDK protocol description (DJI)

`room_companion/camera/rsdk.py` is written from the protocol description that DJI publishes in
<https://github.com/dji-sdk/Osmo-GPS-Controller-Demo> (`docs/protocol.md`,
`docs/protocol_data_segment.md`). Those documents are offered under DJI's End User License
Agreement (<http://developer.dji.com/policies/eula/>); none of their text or of the demo's code is
included here.
