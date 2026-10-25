# Connect room-companion to HipiMind

[HipiMind Room](https://hipimind.com/room) shows a room-companion on a web page you can open from
anywhere: the three switches, a live view while the page is open, "what the AI sees", reminders,
and the choice of model for each job. room-companion keeps doing all the capturing and, unless you
pick HipiMind's cloud models, all the thinking. It opens one outgoing WebSocket to HipiMind; no
port forwarding, public IP or VPN is needed.

The wire protocol is HipiMind's "connect your own room device" contract:
<https://hipimind.com/room/connect>. This page is about room-companion's side of it.

## What leaves the machine

Only to your HipiMind account:

- the three switches, and whether the camera, microphone and each model are running, plus a one-line
  summary the connector writes from those same facts (never the local status text, which names
  hardware and carries capture errors);
- the current scene label and its short note ("what the AI sees" — text, never an image);
- reminder categories, switch changes, scene changes (at most one every 10 minutes) and a few
  notices (camera missing, model paused for heat). A switch change also carries
  `data: {"changes": {...}, "source": ...}`, where the source is a fixed code — `web` (the HipiMind
  website), `local` (the device's own page), `voice`, `feishu` or `device` — never an address. Event
  text is written in the language chosen on the HipiMind page (`config.language`, `zh` or `en`);
  the website renders switch events from `data` in the reader's language;
- the model settings you chose (server address and model name; **never a key**);
- JPEG frames, **only while you have the HipiMind page open and asked for live video**;
  HipiMind forwards them to your browser and keeps nothing.

Never sent: transcripts, audio, the local event log as such, process ids, device or speaker names,
client addresses, capture error output, logs, user names or passwords in a server address.
A slot you set to `cloud` sends that job's input (a frame, an utterance, a reminder's text) to
HipiMind's model; see "Models" below.

## 1. Install

```bash
pip install 'room-companion[hipimind]'          # adds websockets (and pillow, for scaling live frames)
# or from a checkout:  pip install -e 'tools/room-companion[hipimind]'
```

## 2. Pair

1. On <https://hipimind.com/room> choose **Add a device**. You get an 8-character code, valid for
   10 minutes.
2. On the machine:

   ```bash
   python -m room_companion pair --code K7QM-2WXH --name "Bedroom"
   ```

   This reads the `hipimind` section of room-companion's config (below) for the server and the
   token file, exchanges the code for a device token, and writes the token to `token_file` with
   mode 600. The token is never printed. It prints which account the camera joined
   (`Paired to a***e@example.com`): if that is not your account, remove the device on the website. Pair again (with a new code) if you remove the device on
   the website or lose the file.
3. If room-companion is already running with a `hipimind` section, it notices the new token
   within 30 seconds and connects; no restart is needed. Otherwise add the section and restart it.
   The website shows the device online within a few seconds of connecting.

## 3. Configure

Add a `hipimind` section to room-companion's `config.json` (in its data directory). Only
`token_file` is needed; everything else has a default.

```json
{
  "hipimind": {
    "server": "https://api.hipimind.com",
    "token_file": "/home/you/.config/room-companion/hipimind.token",
    "live": { "max_fps": 2, "max_width": 960, "jpeg_quality": 70 },
    "events": { "reminders": true, "switches": true, "scene": true, "notices": true },
    "scene_event_min_minutes": 10
  }
}
```

JSON Schema of the section:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "room-companion hipimind section",
  "type": "object",
  "required": ["token_file"],
  "properties": {
    "server": { "type": "string", "format": "uri", "default": "https://api.hipimind.com",
                "description": "HipiMind API base URL" },
    "ws_url": { "type": ["string", "null"], "default": null,
                "description": "Override the WebSocket URL; default is server with ws(s):// and /ws/room/device" },
    "token_file": { "type": "string", "description": "Where `pair` writes the device token (mode 600)" },
    "platform": { "type": ["string", "null"], "default": null,
                  "description": "Shown on the website; detected (linux, windows-wsl, macos) when null" },
    "poll_seconds": { "type": "number", "minimum": 0.2, "default": 1.0,
                      "description": "How often the state is re-read; a change is sent at most once a second" },
    "live": {
      "type": "object",
      "properties": {
        "max_fps": { "type": "number", "exclusiveMinimum": 0, "default": 2 },
        "max_width": { "type": "integer", "minimum": 160, "default": 960 },
        "jpeg_quality": { "type": "integer", "minimum": 30, "maximum": 95, "default": 70 }
      }
    },
    "events": {
      "type": "object",
      "properties": {
        "reminders": { "type": "boolean", "default": true },
        "switches": { "type": "boolean", "default": true },
        "scene": { "type": "boolean", "default": true },
        "notices": { "type": "boolean", "default": true }
      }
    },
    "scene_event_min_minutes": { "type": "number", "minimum": 0, "default": 10 }
  }
}
```

A complete config for a Windows PC running room-companion in WSL, with HipiMind and the
recommended local models, is in [`examples/config.hipimind.json`](../examples/config.hipimind.json).

### Run it as a service

The service file in [`examples/room-companion.service`](../examples/room-companion.service) needs
no change: the connector runs inside the app. Check it with `journalctl --user -u room-companion`:
`connected to HipiMind as device …` means it is up.

## 4. Models

Each job has its own model, chosen in the `models` section of the config or on the HipiMind page
(**Models**). A choice made on the page wins over the config file and is kept in
`<data_dir>/state/models.json`; keys typed on the page are kept in `<data_dir>/state/model_keys.json`.
Both files are mode 600 and HipiMind does not keep the keys. A key belongs to the server address
it was typed for: moving a slot to another address does not take the key along (type it again
for the new server); moving back to the first address uses it again.

**Language.** `config.language` (`zh` or `en`, in `welcome` and in `config`) sets the language the
device writes event text in and speaks reminders in; it is kept in `<data_dir>/state/overrides.json`.
Without it the device keeps its own: the config file's top-level `"language"`, default `zh`.

Changes made on the page while the device was offline arrive when it reconnects (the server sends
them in `welcome`). From `welcome`, a part that is missing or `null` leaves the device's own
setting alone — it can set quiet hours, never clear the ones in the config file.

| slot | does | `openai` source calls |
|---|---|---|
| `vision` | looks at a frame now and then and names the scene | `POST {base_url}/chat/completions` with the frame as an `image_url` data URL, asking for the scene JSON (structured output when the server has it, plain text otherwise) |
| `stt` | speech to text (wake word, spoken commands); the local VAD still cuts the utterances | `POST {base_url}/audio/transcriptions`, multipart, the utterance as 16 kHz WAV |
| `tts` | speaks reminders | `POST {base_url}/audio/speech` with `"response_format": "wav"` |

| source | meaning |
|---|---|
| `engine` (default) | the built-in engines: llama.cpp `llama-server` for vision (started only while AI and video are on), sherpa-onnx SenseVoice for speech-to-text, sherpa-onnx MeloTTS for speech |
| `openai` | any OpenAI-compatible server **this machine** can reach: localhost, your LAN, a server you host, or a provider with your key. HipiMind never connects to it |
| `cloud` | HipiMind's cloud models, over the same WebSocket; counted against your HipiMind plan |
| `off` | nobody (no spoken reminders, no voice commands, or no AI looking) |

Rules that do not change with the source:

- **Nothing goes to any remote model while the AI switch is off.** For `stt` and `tts` with
  `openai` or `cloud`, nothing is sent while AI is off: no utterances, and no text to speak
  (spoken reminders and replies stay silent; notifications still go out). With `engine`, speech
  is recognized and spoken locally whatever the AI switch says, as before.
- A base URL must be a plain `http://` or `https://` address with a host name — no other scheme,
  no user name or password in it, no `#`. Redirects are not followed, an answer is read up to
  2 MB (8 MB for speech audio), and each request must finish within about twice its timeout.
- `cloud` requests fit HipiMind's limits: a frame is scaled to at most 768 px on the long side
  and 300 KB (Pillow needed for frames bigger than that), and an utterance longer than 30 s is
  cut to its first 30 s. A request that would still be too large is refused on the device,
  never sent (the server would close the connection).
- A failing model never takes room-companion down: vision answers nothing, speech is dropped, and
  the slot shows `error` on the website.

```json
{
  "models": {
    "vision": { "source": "openai", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen2.5vl:3b" },
    "stt":    { "source": "engine" },
    "tts":    { "source": "openai", "base_url": "http://192.168.1.20:8000/v1",
                "model": "speaches-ai/Kokoro-82M-v1.0-ONNX", "voice": "af_heart" }
  }
}
```

ModelSlot fields: `source`; for `openai`: `base_url` (ending in `/v1`), `model` (exactly as the
server names it; `GET {base_url}/models` lists them), `voice` (tts), `language` (stt, optional),
`api_key_file` (config file only: a file holding the key).

### Test connection

The **Test connection** button on the website makes one small real request with the setting you
are looking at, without saving it: a 64×64 image and "Reply with OK" for vision, one second of
silence for speech-to-text, the word "test" for speech. For `engine` it checks the engine's files,
and makes a real call when the engine is already running. The answer is the model's name and the
time it took, or one of: `connect_failed`, `timeout` (15 s), `unauthorized` (wrong or missing key),
`not_found` (usually a base URL without `/v1`), `model_not_found`, `bad_response`,
`engine_unavailable`, `unsupported`. A `cloud` refusal is reported as `unsupported` (not on your
plan or not enabled) or `connect_failed` (allowance used, rate limited, unavailable), with
HipiMind's own code in the message.

## 5. Connect your own model

### The recommended local setup (Models → Recommended (local))

What the reference room runs: one PC with an NVIDIA GPU (about 4.5 GB of free video memory).
Measured on a laptop RTX 3060: one look at a 1280×720 frame takes about 4 s, video memory
4.3–4.5 GB, the model server's own memory about 1 GB.

| part | file | source | SHA-256 |
|---|---|---|---|
| vision server | llama.cpp `llama-server`, release b11871 (CUDA 12.4 build) | <https://github.com/ggml-org/llama.cpp/releases/tag/b11871> | compare with the release page's digest |
| vision model | `Qwen3VL-4B-Instruct-Q4_K_M.gguf` (2.50 GB) | <https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF> | `66358cb18bb6b3b1b6675aa412c7a88ef01d228f481184d13668e5201c730a0a` |
| vision projector | `mmproj-Qwen3VL-4B-Instruct-F16.gguf` (0.84 GB) | same repository | `256f3a43bd4205ffef48d6b92715e1e70b5b0e9aef06522584967513a9985331` |
| voice activity | `silero_vad.onnx` | <https://github.com/k2-fsa/sherpa-onnx/releases/tag/asr-models> | `9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6` |
| speech to text | SenseVoice-Small int8: `model.int8.onnx`, `tokens.txt` (`sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17`), sherpa-onnx 1.13.8 | same page | `c71f0ce00bec95b07744e116345e33d8cbbe08cef896382cf907bf4b51a2cd51`, `f449eb28dc567533d7fa59be34e2abca8784f771850c78a47fb731a31429a1dc` |
| speech | MeloTTS zh_en (`vits-melo-tts-zh_en`): `model.onnx`, `tokens.txt` | <https://github.com/k2-fsa/sherpa-onnx/releases/tag/tts-models> | `bf30582eb1b012250a35b1a4a80e7dfbcf8485e7bb9de0d95efbbeef0e4ad86d`, `d18664a7e12bd7ea1022ddaf951e534e136815016c5a809d6b64156bffb4369d` |

Steps:

1. Download the files and check them: `sha256sum <file>`.
2. Put the vision files where Windows can read them, and the speech files in WSL, and fill in the
   `llama`, `asr_dir`, `vad_model` and `tts` settings as in
   [`examples/config.hipimind.json`](../examples/config.hipimind.json).
3. Create the key file for the vision server (one line of random text) and point
   `llama.key_file`/`key_file_win` at it. room-companion starts the server itself, bound to
   127.0.0.1 and protected by that key, only while AI and video are on — the same as running
   `llama-server -m Qwen3VL-4B-Instruct-Q4_K_M.gguf --mmproj mmproj-Qwen3VL-4B-Instruct-F16.gguf -ngl 99 -c 4096 -np 1 --host 127.0.0.1 --port 8791 --api-key-file api.key --no-webui`.
4. Leave every slot on `engine` (or choose **Recommended (local)** on the website) and press
   **Test connection** for each.

### Ollama

```bash
ollama pull qwen2.5vl:3b
ollama serve                         # 127.0.0.1:11434
```

Vision → `openai`, base URL `http://127.0.0.1:11434/v1`, model `qwen2.5vl:3b`, no key. Ollama has
no speech endpoints: keep `stt`/`tts` on `engine`, or use a speech server such as
[Speaches](https://github.com/speaches-ai/speaches) (`http://127.0.0.1:8000/v1`, model
`Systran/faster-whisper-small` for `stt`, `speaches-ai/Kokoro-82M-v1.0-ONNX` for `tts`).

### vLLM, LM Studio, llama.cpp elsewhere, or a hosted provider

Anything that speaks the OpenAI API: `vllm serve <model>` (`http://<host>:8000/v1`), LM Studio
(`http://127.0.0.1:1234/v1`), `llama-server` on another machine, or a provider's URL with your key.
Fill in base URL, model, and key (on the website, or `api_key_file` in the config), then press
**Test connection**. A provider bills you for what room-companion sends it: one frame per minute
while something moves, every 5 minutes otherwise.

## 6. Sidecar mode

For a room-companion you cannot change (or an older build with the same local HTTP API), run the
connector next to it:

```bash
python -m room_companion.hipimind pair --server https://api.hipimind.com --code K7QM-2WXH \
  --name Bedroom --token-file ~/.config/room-companion/hipimind.token
python -m room_companion.hipimind run --config ~/.config/room-companion/hipimind-sidecar.json
```

The sidecar config is the `hipimind` section above plus `"local_api": "http://127.0.0.1:8790"`
(and `local_api_key_file` if that address is not loopback); see
[`examples/hipimind-sidecar.json`](../examples/hipimind-sidecar.json). It forwards switches, state,
events and live video; model choice and Test connection need the in-process connector.

## 7. Troubleshooting

| log line / website | what it means |
|---|---|
| `HipiMind refused the device token` (in the app) / `stopped: 4401 …` (sidecar) | the device was removed on the website, or the token file is wrong: pair again. Inside the app the connector waits for the new token and reconnects by itself; the sidecar exits |
| `4403 … Room is not enabled for this account` | HipiMind Room is not open to your account yet |
| `4409 … another connection for this device replaced this one` | two copies run with the same token; stop one |
| `reconnecting in N s` | normal after a network drop or a HipiMind restart; it backs off up to 60 s |
| `waiting for a device token` (in the app) / `no device token; run the pair command first` (sidecar) | `token_file` is missing or empty: run `pair` |
| website: device offline | the app is not running, the network is down, or the token was revoked |
| website: live view stays black | video is off, the camera is missing, or the frames are larger than the limit (lower `live.max_width`) |
| a slot shows `error` | press **Test connection** for the reason |
