# room-companion

A room companion built from a webcam and a microphone: it watches one room, recognizes what the
person in it is doing (laundry, cooking, coding, working on a router, yoga, phone on the sofa,
sleeping), and now and then says something useful. Everything runs on your own machine: speech
recognition and the vision model are local, and nothing (frames, audio, transcripts) is sent to a
cloud model. Only the short reminder texts and switch confirmations go to the notifier you pick
(the default only prints them). That is the default; each model (vision, speech-to-text, speech)
can instead be any OpenAI-compatible server you choose, or be turned off (see [Models](#models)),
and the whole thing can be watched and switched from a web page anywhere through HipiMind (see
[Connect to HipiMind](#connect-to-hipimind)).

Three switches are independent and are the point of the design:

| Switch | Off means | How you can check it is really off |
|---|---|---|
| Video | The capture process that holds the camera has exited; frames in memory are dropped | No capture process in the process table; on Windows another program can open the camera right away |
| Audio | The recorder has exited; queued audio and transcripts are dropped | No recorder process; on Linux `/proc/asound/cardN/pcm0c/sub0/status` is `closed`; on Windows the mic's usage record gets a stop time |
| AI | Nothing reaches a model; the local model server process does not exist | The model server is gone from the process table; the gate's `sent` counter stops |

Switch state is written to disk before a switch is turned on; an unreadable or corrupt state file
counts as "all off". Every change, from the web page, the text API or a voice command, produces one
confirmation message, sent only after the capture process has actually stopped or started.

## How it works

```
camera ──ffmpeg──> 5 fps JPEG (live view) ──> motion score ──┐
                                                             ├─> one frame now and then ──AI gate──> local vision model
mic ──recorder──> 16 kHz PCM ──> VAD ──> local ASR ──> voice commands, "talking" signal │                (OpenAI-compatible,
                                                                                         │                 e.g. llama.cpp)
                                                    scene label <────────────────────────┘
                                                        │
                                                 reminder policy ──> speaker (local TTS) + notifier
```

- **Capture**, two back ends with the same pipelines:
  - `capture: "linux"`: v4l2 camera (UVC) and ALSA microphone. Device nodes are created on hot-plug,
    so a container only needs the video4linux (81) and ALSA (116) device classes.
  - `capture: "dshow"`: for a Windows PC running the app inside WSL. The devices stay Windows devices;
    Windows `ffmpeg.exe` reads them through DirectShow and is started from WSL. Killing the WSL side
    ends the Windows process too, which is what releases the device. No USB passthrough, no driver,
    no Windows service. Devices are picked by name (`video_prefer`, `audio_prefer`). Motion is scored
    from the live JPEG frames. After WSL restarts, a systemd service can be left with a broken interop
    channel (every `.exe` fails with "Invalid argument"); the app then picks a working socket from
    `/run/WSL` by itself and shows it under `interop` in `/api/status`.
- **Microphone fallback**: if the preferred microphone disappears, or stays digitally silent for
  10 minutes, recording moves to the next name in `audio_prefer`, and moves back when the preferred
  one returns. The change is announced at most 4 times a day and never during quiet hours.
- **Speech**: Silero VAD cuts utterances, SenseVoice-Small (int8, via sherpa-onnx) transcribes them on
  the CPU. Transcripts live in memory for 10 minutes and are never written to disk.
- **Vision**: any OpenAI-compatible server that takes images. The included manager starts llama.cpp's
  `llama-server` only while the AI and video switches are both on, binds it to 127.0.0.1 with an
  API key file, and stops it otherwise. Crashes back off (30 s doubling to 10 min). On an RTX 3060
  Laptop GPU, Qwen3-VL-4B-Instruct Q4_K_M with the F16 projector uses about 4.4 GB of GPU memory and
  takes about 4 s per 1280x720 frame. While it runs, the GPU temperature is logged every 5 minutes and
  the model pauses for 30 minutes at 85 °C.
  The model returns a JSON scene label (schema-constrained): `laundry`, `cooking`, `coding`,
  `router`, `yoga`, `sofa_phone`, `sleeping`, `other`, `empty`, plus `hot_oil` and `on_phone_call`.
  One frame per minute while something moves, every 5 minutes otherwise.
- **Reminder policy** (`policy.py`): reminders come from fixed rules on how long a scene has lasted
  (e.g. 90 minutes of coding, 45 minutes of phone on the sofa, laundry done after 45 minutes, kitchen
  check after cooking, water after yoga). When to say them is the strict part:
  - quiet hours (default 23:00-08:00), asleep, or nobody in the room: nothing;
  - talking, on a phone call, cooking with hot oil, in the middle of yoga: wait;
  - coding or router work: wait until there has been a 2-minute break;
  - at most 6 a day, each kind once a day;
  - replying "不用" turns that kind off for the day, "别再提醒这个" turns it off for good;
  - a short summary of yesterday and last night at 08:30;
  - modes: 安静 (notifier only, no speech), 平衡, 主动 (earlier thresholds).
  Only scene labels and minutes are kept (`state/policy.json`).
- **Speaking** (optional): local Chinese TTS (sherpa-onnx, e.g. MeloTTS zh_en, which also reads English
  words) on the CPU. `winplay.ps1` plays it straight to one Windows output (WASAPI shared mode) without
  changing the default device. The output is picked by name from `tts.output_prefer`, or chosen on the
  page; with nothing preferred, Windows' default is used. A muted or quiet output is raised to
  `tts.volume` (default 70%) while speaking and put back afterwards. The output's peak meter during
  playback is kept as proof that it played. `tts.output_labels` gives outputs short names, and
  `tts.missing_notes` adds a line for a preferred device that is not connected. Speech the mic picks up
  while we are speaking (any segment that overlaps playback) is dropped before recognition, so it is
  never a command, a transcript, or "someone is talking".
- **Reading typed text out loud**: the page has a text box, and the text command `播报：<text>` does
  the same. It works with all three switches off. At most 300 characters, 6 a minute and 200 a day.
  Events record only the length and where it came from; the words stay in memory for the day.
- **Notifiers** (`notifiers/`): `log` (default, prints) or `feishu` (optional plugin: a custom app bot
  messaging one user; needs `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_OPEN_ID`). Adding one is a
  class with `send(text)`.

## Web page and API

A small page (Chinese UI) shows the three switches, a live view, the current scene, reminders,
the audio level, recent transcripts and an event list.

It listens on `0.0.0.0:8790` by default (`listen`, `port` in the config).

- `127.0.0.1` needs no key (other services on the same machine). A request that came through a reverse
  proxy (it carries `X-Forwarded-For`) is treated as remote.
- Addresses in `allowed_cidrs` (default: the Tailscale ranges) need the key: `?k=` once (turned into
  an HttpOnly cookie), or `Authorization: Bearer`. Everything else is refused.
- For every caller, the local one included, so that a web page open in a browser on the same machine
  can neither change a switch nor read anything:
  - the `Host` header must be `127.0.0.1`, `localhost`, `[::1]` or a name in `allowed_hosts` (add the
    name your reverse proxy serves); this stops DNS rebinding;
  - a request the browser marks `Sec-Fetch-Site: cross-site` is refused, except following a link to the
    page itself; the page cannot be framed;
  - a `POST` needs the header `X-Room-AI: 1` and `Content-Type: application/json`, and its `Origin`, if
    sent, must be one of the allowed hosts. A cross-site form can send neither header.
- `POST /api/switch {"video": false}`, `POST /api/command {"text": "隐私模式"}`, `GET /api/status`,
  `GET /snapshot.jpg`, `GET /stream.mjpg`.
- `POST /api/broadcast {"text": "...", "id": "optional"}` answers at once with `{"ok", "id", "message"}`;
  when it is refused, `code` is `empty`, `too_long`, `rate_limited` (429), `busy` or `no_output` (503).
  `GET /api/broadcast/<id>` gives `state` (`queued`, `speaking`, `done`, `failed`), `output`, `seconds`,
  `peak` and `error`. In-process connectors call `app.broadcast(text, source, request_id=, on_done=)`
  and get the same result fields through `on_done` once it has been played.
- `POST /api/output {"choice": "auto" | "<output name>"}` picks where it speaks; the choice is kept in
  `state/output.json`.
- A remote caller can't name its own source in confirmations and events; `source_names` maps known
  addresses (for example a bot on another machine) to a name.
- Loopback-only self-test hooks: `/api/selftest/inject` (16 kHz PCM into the microphone path),
  `/api/selftest/unplug` (pretend devices are gone for N seconds), `/api/speak`.

Voice and text commands understand the same sentences: `关视频`, `视频和声音都关掉`, `开AI`,
`隐私模式` (all off), `全开`, `状态`, `安静模式`, `不用`, `别再提醒这个`, `恢复提醒`.
Voice commands need the wake word (default `房间助手`; 1-3 misheard characters followed by `助手` at
the start of a sentence also count, because recognizers often mishear the first word).

## Cameras

Any UVC webcam works. Tested with a DJI Osmo Action 5 Pro in its official USB webcam mode (it
enumerates as `05c6:8004`, MJPEG/H.264 up to 1920x1080 at 30 fps, with a USB audio interface; a DJI
Mic Mini paired to the camera comes through that interface). The camera has to be switched into
webcam mode on its own screen, and again after it loses power; when video is on but the camera has
been missing for 3 minutes, a notification asks for that. Only the official webcam mode is used
here. For remote control of the camera itself, DJI publishes an official Bluetooth protocol demo
([dji-sdk/Osmo-GPS-Controller-Demo](https://github.com/dji-sdk/Osmo-GPS-Controller-Demo)); it does
not offer webcam or streaming control, so it is not needed for this.

## Running it

### What the machine needs

- Python 3.10 or newer.
- `capture: "linux"`: `ffmpeg`, `v4l2-ctl` (v4l-utils) and `arecord` (alsa-utils).
- `capture: "dshow"` (the app in WSL, the devices on Windows): Windows `ffmpeg.exe` (path in `ffmpeg_exe`),
  Windows PowerShell (built in, used for playback and for reading the default output device),
  `llama-server.exe` from a llama.cpp Windows release with its CUDA runtime DLLs next to it, and the NVIDIA
  driver (`nvidia-smi.exe`, used for the GPU temperature).

### Models

None are included. Download them yourself and check each file against the publisher's sha256.

| Model | Where to get it | Where it goes (config key) |
|---|---|---|
| SenseVoice-Small, int8 (speech recognition) | `model.int8.onnx` and `tokens.txt` from [csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17](https://huggingface.co/csukuangfj/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17) | a folder holding those two files (`asr_dir`) |
| Silero VAD | [`silero_vad.onnx`](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/silero_vad.onnx) | the file (`vad_model`) |
| MeloTTS zh_en (speaking, optional) | [`vits-melo-tts-zh_en.tar.bz2`](https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-melo-tts-zh_en.tar.bz2), unpacked | the unpacked folder (`tts.model_dir`) |
| Qwen3-VL-4B-Instruct (vision, optional) | `Qwen3VL-4B-Instruct-Q4_K_M.gguf` and `mmproj-Qwen3VL-4B-Instruct-F16.gguf` from [Qwen/Qwen3-VL-4B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF) | `llama.model`, `llama.mmproj` (Windows paths when `llama-server.exe` runs on Windows) |
| llama.cpp server | a release from [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp/releases) (on Windows with an NVIDIA GPU: the `win-cuda` build plus the matching `cudart` archive) | `llama.exe` |

```
models/
  sense-voice/model.int8.onnx
  sense-voice/tokens.txt
  silero_vad.onnx
  tts/vits-melo-tts-zh_en/...        (optional)
```

Without the vision model the AI switch has nothing to send to, and nothing leaves the gate. Without TTS,
reminders only go to the notifier.

### Starting it

Run these from `tools/room-companion`:

```
pip install ".[all]"            # sherpa-onnx, numpy, pillow
mkdir -p data && cp examples/config.windows-wsl.json data/config.json   # or config.linux.json; then fix the paths
ROOM_COMPANION_DATA_DIR=$PWD/data ROOM_COMPANION_WEB_TOKEN=... python -m room_companion
```

All three switches start off. State and event summaries go under the data directory.
`examples/room-companion.service` is a systemd user unit (MemoryMax 3G); with a lingering user it
starts whenever the machine (or WSL) starts. `examples/roomctl-remote` controls it over the network
with the key read from a file, never from the command line.

## What is stored

| Data | Stored? | Retention |
|---|---|---|
| Video, audio | No. Only the latest frame and the utterance being recognized are in memory | Dropped when the switch turns off |
| Transcripts | No, memory only | 10 minutes; dropped when audio turns off |
| Text read out loud | No, memory only | That day |
| Frames sent to the vision model | No | Only for the one local request |
| Event summaries (`events/*.jsonl`): switch changes, device in use/released, motion start/end, seconds of speech (no words), scene labels, reminder kinds, GPU temperature, text read out loud (length and source, no words) | Yes | 30 days |
| `state/policy.json`: minutes per scene per day, sleep/wake time, reminder kinds given or turned off | Yes | Minutes: 3 days |
| `state/models.json`, `state/model_keys.json` (mode 600): model choices and keys made at run time | Yes, only if you choose models at run time | Until changed |
| `state/overrides.json`: quiet hours set at run time | Yes, only if set at run time | Until changed |

## Models

Three jobs, each with its own source, set in the config's `models` section (or at run time from
the HipiMind page):

| slot | `engine` (default) | `openai` |
|---|---|---|
| `vision` | `llama-server` managed as above | `POST {base_url}/chat/completions` with the frame as an image |
| `stt` | SenseVoice-Small via sherpa-onnx | `POST {base_url}/audio/transcriptions` (the local VAD still cuts utterances) |
| `tts` | MeloTTS via sherpa-onnx | `POST {base_url}/audio/speech`, WAV |

`openai` means any OpenAI-compatible server this machine reaches: Ollama, vLLM, LM Studio,
`llama-server` elsewhere, a speech server such as Speaches, or a hosted provider with a key
(`api_key_file`). `cloud` uses HipiMind's models through the HipiMind connector, and `off` turns
the job off. Nothing goes to any remote model while the AI switch is off; with `stt` or `tts` on
`openai` or `cloud` that includes speech, so voice commands and spoken reminders then need AI on.
A base URL must be a plain `http(s)://` address (no credentials, no `#`), and a key stays with the
address it was typed for. With no `models` section every slot is `engine` and nothing changes. Details, config examples and the recommended downloads with
their checksums: [docs/hipimind.md](docs/hipimind.md#4-models).

```json
"models": {
  "vision": { "source": "openai", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5vl:3b" },
  "stt":    { "source": "engine" },
  "tts":    { "source": "off" }
}
```

## Connect to HipiMind

[HipiMind Room](https://hipimind.com/room) puts this on a web page you can open from anywhere —
switches, a live view while the page is open, "what the AI sees", reminders, and the model for each
job with a **Test connection** button — over one outgoing WebSocket (no port forwarding).

```
pip install ".[hipimind]"
python -m room_companion pair --code K7QM-2WXH --name Bedroom   # code from hipimind.com/room
# prints "Paired to a***e@example.com": check it is your account
```

then add `"hipimind": {"token_file": "…"}` to the config and restart. What is sent (and what never
is), the config schema, sidecar mode for builds you cannot change, and troubleshooting:
[docs/hipimind.md](docs/hipimind.md). The protocol: <https://hipimind.com/room/connect>.

## Tests

From `tools/room-companion`:

```
python -m unittest discover -s tests -t .
```

84 tests. They use fake ffmpeg/recorder scripts, a fake model server and a fake notifier; they open no
device and make no network request. To be sure, run them with the network cut. Loopback has to be up,
because the web tests talk to a server on 127.0.0.1:

```
unshare -rn sh -c 'ip link set lo up && python -m unittest discover -s tests -t .'
```

## License

MIT, for the code in this folder.

Nothing below is bundled; these are the things the README tells you to download, under their own terms:

| Component | License |
|---|---|
| SenseVoice-Small weights | [FunASR Model Open Source License v1.1](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE). Not an OSI license: it requires attribution and keeping the model names, says the weights are "provided for reference and learning purposes only", and the licensor may revise it. Read it before any commercial use. |
| sherpa-onnx | Apache-2.0 |
| Silero VAD | MIT |
| MeloTTS | MIT |
| Qwen3-VL-4B-Instruct | Apache-2.0 |
| llama.cpp | MIT |
| ffmpeg | LGPL-2.1 or GPL, depending on the build |
