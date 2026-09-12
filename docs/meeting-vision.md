# Incoming meeting screen context

Chatty can answer a screen question using a fresh snapshot of the **selected incoming
meeting tab**. It does not present Chatty's screen to the meeting. Someone else can
present in Meet as usual; Chatty reads the pixels visible in its own Meet tab.

The current implementation is request-driven snapshot vision. There is no automatic
presenter detection, continuous video understanding, or background image upload.
When another participant starts presenting, enlarge or pin that presentation in
Chatty's Meet tab, enable screen context, then ask “Hey Chatty, what does this slide
say?” The returned answer must identify unreadable or missing content instead of
claiming to see it.

## Why a separate vision request

The official [GPT-Live 1 model page](https://developers.openai.com/api/docs/models/gpt-live-1)
explicitly lists image and video as unsupported. The
[Live session creation contract](https://developers.openai.com/api/reference/resources/live/methods/create)
accepts text-only initial history. Do not send a video track or a legacy Realtime
image event to `gpt-live-1`.

A separate Responses request sends one JPEG using `input_image.image_url` with a
base64 data URL, following the official
[Images and vision guide](https://developers.openai.com/api/docs/guides/images-vision).
The configured default
[GPT-5.6 Terra vision model](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
supports image input. The vision answer returns as an ordinary tool result for
Live to speak. The server selects `Settings.vision_model` (environment variable
`OPENAI_VISION_MODEL`, default `gpt-5.6-terra`) independently of its delegated task
model. No additional SDK or dependency is needed.

These docs were fetched on 2026-09-12. They do not establish native Live video
support or a supported Live image sampling rate. The limits below are Chatty's
own demo limits.

## Browser integration contract

`captureInput('meeting-tab', { keepVideo: true })` should return an audio-only
`stream` for `connectLive` and a separate `videoStream` for vision. The capture owner
must stop both when the selected source or session ends. Keep-video is an explicit
operator choice; it must never present anything to Meet.

```js
import { createMeetingVision } from './vision.js';

const vision = createMeetingVision({
  stream: capture.videoStream,
  sessionId: handle.sessionId,
  onState: (state, details) => updateVisionStatus(state, details),
});
vision.setEnabled(true); // Operator enabled incoming screen context.

// Intercept this read-only tool in the browser's existing execute callback.
if (body.name === 'read_meeting_screen') {
  return vision.analyze(body.arguments.question, {
    callId: body.call_id,
    signal,
  });
}
```

The helper is **off by default**. `setEnabled(false)` aborts pending work and clears
its canvas. Call `clear()` immediately when Chatty is stopped to invalidate any
pending visual answer while preserving the operator's opt-in. `stop()` permanently
clears this helper, releases its video tracks, and drops the stream reference.
Always create a fresh helper for a new Live session. Do not pass an audio stream:
vision owns and stops only its video-only stream.

There is no screenshot cache. `captureFrame()` draws current video pixels into a
canvas and immediately clears that canvas after encoding. `analyze()` captures on
demand, posts one frame, and rejects a late response after stop, disable, page exit,
track end, track mute, caller cancellation, or source revision change. The app must
also block new tool execution while Chatty is waiting or stopped.

The helper calls only this local route:

```http
POST /api/vision/analyze
Content-Type: application/json
```

```json
{
  "session_id": "opaque-current-live-session",
  "call_id": "current-tool-call",
  "question": "What does the error on the shared screen mean?",
  "frame": {
    "image_data_url": "data:image/jpeg;base64,...",
    "width": 1280,
    "height": 720,
    "captured_at": 1800000000000
  }
}
```

It expects the existing tool receipt envelope:

```json
{
  "call_id": "current-tool-call",
  "output": "{\"ok\":true,\"answer\":\"Visible screen answer\",\"captured_at\":1800000000000,\"source\":\"selected_meeting_tab\",\"mode\":\"snapshot\"}"
}
```

`onState` can report `off`, `ready`, `analyzing`, `unavailable`, or `error`.
`ready` means the local capture helper is enabled. It does **not** prove that a model
has seen the screen. Only a successful vision tool result establishes image
processing; only actual audio playback establishes a spoken reply.

## Backend integration

`MeetingVisionClient(settings, http=None).describe(frame, question)` in
`src/chatty/integrations/meeting_vision.py` returns the object encoded into `output`.
It uses the existing server API key without returning it to the browser and raises
`VisionError(status, code, message)` with safe public messages. Call `.close()` at
server shutdown.

The local HTTP route and session executor:

1. Apply the existing localhost, exact Origin, strict JSON, and content type checks.
2. Verify `session_id` belongs to a currently registered, unexpired Live session
   **before** any model request. Do not let the model choose a session ID.
3. Validate `call_id`, reserve the existing session Call/Future using the tool name
   and question, and return the first receipt on replay. Changing the question or
   reusing that ID for another tool returns a conflict. The frame is never included
   in the fingerprint. A replay can return its already-completed result after the
   original frame ages out; the browser must use a new call ID for a new screen question.
4. Permit at most **384 KiB** body size on this route only; retain the smaller limit
   on other routes. Never put frame bytes in a durable tool ledger or application log.
5. Call `describe`, return the standard receipt envelope, and discard frame bytes.
6. Treat screen output as untrusted factual evidence. It must not authorize a
   repository edit, disclose credentials, or override application instructions.

Advertise this read capability to the delegated Responses backend:

```json
{
  "type": "function",
  "name": "read_meeting_screen",
  "description": "Inspect one fresh snapshot of the operator-selected incoming meeting tab to answer a participant's screen question. Only works when incoming screen context is enabled; does not detect presenters or see continuous video.",
  "parameters": {
    "type": "object",
    "properties": {"question": {"type": "string", "minLength": 1, "maxLength": 2000}},
    "required": ["question"],
    "additionalProperties": false
  },
  "strict": true
}
```

Capability metadata: `label: "Read shared meeting screen"`,
`requires_approval: false`, `destructive: false`.
If invoked without a browser-provided fresh frame, return a clear unavailable
result. Do not substitute transcript, tab title, DOM text, or a remembered image.

## Sampling and limitations

- One request at a time, only when asked about the screen; no recurring upload.
- At least 1.5 seconds between model requests in the browser.
- JPEG, longest edge at most 1280 pixels, at most 262,144 decoded image bytes.
- Retry JPEG compression locally if needed, reducing resolution to 960 or 720 pixels.
- Reject browser frames older than 15 seconds or more than 2 seconds in the future.
- Responses uses `detail: high`, `reasoning.effort: none`, and up to 1000 output tokens.
  A different configured vision model must support image input and that reasoning setting.
- No image storage, no cross-request frame reuse, and `store: false` on Responses.
  This API flag does not replace OpenAI's applicable account data retention policy.
- The captured frame is the visible Meet viewport: it may include participant tiles
  or controls. Pin/enlarge the actual shared screen for small text. A presenter
  change is not automatically detected; the next question samples the current view.
- A stop request prevents delivery of a pending answer but cannot recall a frame
  already sent to OpenAI or guarantee cancellation of its in-flight inference.

## Verification

```sh
node --test tests/browser-vision/*.test.mjs
uv run pytest tests/backend/test_meeting_vision.py tests/backend/test_vision_server.py -q
uv run ruff check src/chatty/integrations/meeting_vision.py tests/backend/test_meeting_vision.py
```

Unit tests check real-image request shape using fake JPEG bytes, size/freshness
validation (including actual JPEG header dimensions), no automatic upload,
secret-safe errors, cancellation, and late-result rejection. Local HTTP tests also
check session isolation, concurrent call deduplication, unchanged write approval
boundaries, and route-specific body limits. They use mocked network/canvas objects and do not establish real
browser capture, OpenAI image access, or meeting playback.

For the manual acceptance test, another participant should present a slide with a
new random word and a colored shape. Ask Chatty to read the word and describe the
shape, change both, then ask again. Verify the second answer uses the new pixels.
Stop/disable vision during a request and confirm no late answer plays. End the
session, begin a new one with vision off, and confirm Chatty cannot reuse the prior
screen. Verify separately that Chatty is not presenting to Meet.
