# room-companion

A room companion built from a webcam and a microphone: it watches one room, recognizes what the
person in it is doing (laundry, cooking, coding, working on a router, yoga, phone on the sofa,
sleeping), and now and then says something useful. Everything runs on your own machine: speech
recognition and the vision model are local, and nothing (frames, audio, transcripts) is sent to a
cloud model. Only the short reminder texts and switch confirmations go to the notifier you pick
(the default only prints them).

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
    from the live JPEG frames.
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
- **Speaking** (optional): local Chinese TTS (sherpa-onnx, e.g. MeloTTS zh_en) on the CPU, played on
  Windows' default output device. While it speaks, transcripts are ignored as echo.
- **Notifiers** (`notifiers/`): `log` (default, prints) or `feishu` (optional plugin: a custom app bot
  messaging one user; needs `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_OPEN_ID`). Adding one is a
  class with `send(text)`.

## Web page and API

A small page (Chinese UI) shows the three switches, a live view, the current scene, reminders,
the audio level, recent transcripts and an event list.

- `127.0.0.1` is trusted (other services on the same machine). A request that came through a reverse
  proxy (it carries `X-Forwarded-For`) is treated as remote.
- Addresses in `allowed_cidrs` (default: the Tailscale ranges) need the key: `?k=` once (turned into
  an HttpOnly cookie), or `Authorization: Bearer`. Changing a switch also needs the header
  `X-Room-AI: 1`, which blocks cross-site form posts. Everything else is refused.
- `POST /api/switch {"video": false}`, `POST /api/command {"text": "隐私模式"}`, `GET /api/status`,
  `GET /snapshot.jpg`, `GET /stream.mjpg`.
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

```
pip install ".[all]"            # sherpa-onnx, numpy, pillow
mkdir -p data && cp examples/config.windows-wsl.json data/config.json   # or config.linux.json
ROOM_COMPANION_DATA_DIR=$PWD/data ROOM_COMPANION_WEB_TOKEN=... python -m room_companion
```

Models are not included: SenseVoice-Small int8 + `tokens.txt`, `silero_vad.onnx`, optionally a
sherpa-onnx TTS model, and for vision a GGUF model with its projector plus `llama-server`
(check every download against the publisher's sha256).
`examples/room-companion.service` is a systemd user unit (MemoryMax 3G); with a lingering user it
starts whenever the machine (or WSL) starts. `examples/roomctl-remote` controls it over the network
with the key read from a file, never from the command line.

## What is stored

| Data | Stored? | Retention |
|---|---|---|
| Video, audio | No. Only the latest frame and the utterance being recognized are in memory | Dropped when the switch turns off |
| Transcripts | No, memory only | 10 minutes; dropped when audio turns off |
| Frames sent to the vision model | No | Only for the one local request |
| Event summaries (`events/*.jsonl`): switch changes, device in use/released, motion start/end, seconds of speech (no words), scene labels, reminder kinds, GPU temperature | Yes | 30 days |
| `state/policy.json`: minutes per scene per day, sleep/wake time, reminder kinds given or turned off | Yes | Minutes: 3 days |

## Tests

```
python -m unittest discover -s tests -t .
```

The tests use fake ffmpeg/recorder scripts, a fake model server and a fake notifier; they open no
device and make no network request. Run them with the network cut (`unshare -n`) to be sure.

## License

MIT
