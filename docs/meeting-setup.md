# Chatty meeting audio

This is the candidate route for the hackathon, not a completed meeting integration. No real Google Meet or OpenAI Live audio session has been verified by this workstream yet. Automated tests use browser fakes; the local harness below allows separate input/output checks without API credentials.

## Route and laptop setup

```text
Teammates on other devices → Meet tab audio → Chatty capture → OpenAI Live
Teammates on other devices ← Meet presentation audio ← Chatty tab ← Live voice
```

Use Chrome on this Mac and localhost or HTTPS for Chatty. Join Meet normally with Munir's account/name, microphone muted and camera optional. Do not choose Present from the pre-join screen: that enters Companion mode, where microphone and speakers are unavailable. Humans join from other devices, preferably using headphones. Keep the laptop's physical microphone muted in Meet, and choose meeting-tab input in Chatty.

1. Join a test Meet normally in one tab. Have a teammate join on another device.
2. Open Chatty in a second tab. Click its Start control with **meeting-tab** selected. In Chrome's chooser select the **Meet tab**, enable **Share tab audio**, then confirm. The chooser is mandatory; the app cannot choose a meeting for you. No audio track means the attempt fails with a useful message.
3. In Meet, choose **Present now → A tab**, select the **Chatty tab**, and enable **Also share tab audio**. The Chatty page remains visible to participants. Do not present the Meet tab back into itself or share system-wide audio.
4. Use the UI's wake/Resume control to allow Chatty speech. Output begins muted, including while Live connects. Keep the visible Stop button available.
5. Have the other participant speak. Verify Live receives the sentence, then that the other device hears Chatty's answer. Listen for repeated self-transcription or echo; mute Chatty immediately if either appears.
6. Repeat with Stop and Resume. Ending the session must release capture; stop presenting separately in Meet.

This sends **presentation audio**, not a virtual microphone. There is no automatic joining, native Zoom/Meet API, Recall dependency, or system audio driver. Do not mute the captured Meet tab itself during the input check; that can affect what the capture receives. Use headphones and the mute control inside Meet to avoid physical microphone feedback.

Chrome may request macOS screen/audio recording permission. Allow the browser when prompted, then retry the chooser if needed. If the audio track or simultaneous capture/presentation route does not work on this machine, report that result immediately. A microphone-only conversation does not pass the meeting demo; the team can decide whether a separately configured virtual audio route is worth trying.

## Backend-independent audio check

Run from the repository root:

```sh
python3 tests/browser-audio/serve.py
```

Open [the local audio harness](http://127.0.0.1:8765/tests/browser-audio/smoke.html) in Chrome. It starts no capture automatically, sends nothing to OpenAI, and writes no recordings. The server binds only to loopback and serves an explicit allowlist of the harness HTML, harness JavaScript, and audio capture module; it cannot browse the repository or serve credentials.

- Select **Microphone (local check)** and click Start to verify the input meter. Stop capture afterward.
- For the meeting route, select **Meet tab** and enable its audio in the chooser. Ask the second-device participant to speak; the meter should move.
- In Meet present the **audio harness tab** with tab audio enabled. Click **Play test tone** here; the second device should hear it. With other people silent and on headphones, the tone should not move this page's input meter. If it does, the return route is feeding output back into input.
- Stop capture, revoke sharing, and start again. Verify the meter stops and permission state recovers.

This checks the two browser audio routes independently of Live. It does not prove transcription, model response, wake/stop policy, tool execution, or final end-to-end behavior.

## UI integration contract

Import `captureInput` from `web/media.js` and `connectLive` from `web/live.js` as browser ES modules. No package installation is required. `captureInput("microphone" | "meeting-tab")` returns `{ stream, stop }`; call it directly from the Start click, before unrelated asynchronous work. It rejects denied permission, absent audio, and known screen/window selections. It removes and stops video tracks immediately; only audio is sent to Live. Revoked capture and page exit release tracks.

```js
const cancellation = new AbortController();
const capture = await captureInput("meeting-tab");
const live = await connectLive({
  stream: capture.stream,
  signal: cancellation.signal, // Optional: cancel startup or close an active session.
  onEvent: handleLiveEvent,
  onState: (state, details) => updateConnectionStatus(state, details),
});
// Exposed only after session.started; pass this exact ID to /api/tools/execute.
console.log(live.sessionId);
// Keep output muted until the UI's wake/Resume policy permits speech.
// From a permitted user gesture, this also retries blocked browser autoplay.
await live.setOutputMuted(false);
// Stop talking immediately, even if a tool call is still pending:
live.setOutputMuted(true);
// To end, allow pending tool results to finish first if the app needs them.
const result = await live.close();
capture.stop();
```

The UI must handle a canceled chooser result: if Stop was clicked while the chooser was open, call `capture.stop()` when it eventually resolves. The browser chooser itself cannot be dismissed by `AbortSignal`. A failed `connectLive` releases the supplied stream; also call `capture.stop()` in the UI's failure cleanup. Avoid passing captured input to a speaker element, which would create feedback.

Transport methods:

| Member | Behavior |
| --- | --- |
| `sessionId` | Opaque string from the backend, checked against `session.started`. |
| `send(event)` | Sends an event object after startup; throws while unavailable or closing. `session.close` is routed through `close()`. No tool execution happens here. |
| `setInputEnabled(boolean)` | Enables/disables outgoing audio tracks. Disabling input prevents wake words from reaching Live; UI decides when to use it. |
| `setOutputMuted(boolean)` | Synchronously changes local playback mute. Returns a playback Promise when retrying unmute. Muting remains effective across late audio tracks; unmute is blocked after close starts. |
| `close()` | Immediately mutes output/disables input. Sends `session.close`, waits up to five seconds for `session.closed`, then releases tracks, playback, channel, and peer. Repeated calls return the same Promise. Resolves `{ finalized, reason, usage?, message? }`. |

`onEvent(event)` receives the original parsed Live event, including transcripts, `response.event`, and final `session.closed`. The UI alone dispatches functions; it must stop submitting new commands once closing starts and ignore stale work from previous sessions. This module does not invent a speech-completed signal or infer voice completion from Responses events.

`onState(state, details)` always includes `details.sessionId` (undefined until the backend answers):

| State | Additional details and meaning |
| --- | --- |
| `connecting` | Startup underway. |
| `ready` | `session.started` received, or a temporary disconnect recovered. |
| `playback-blocked` | `message`: UI should offer a Resume click that calls `setOutputMuted(false)`. |
| `reconnecting` | `message`: temporary WebRTC interruption; fail after five seconds if not recovered. |
| `closing` | No new commands; output muted, input disabled. |
| `error` | `message`: startup, transport, or capture failure; render as text. |
| `closed` | `finalized`, `reason`, optional `usage`/`message`. `finalized: true` requires `session.closed`; a socket close or timeout cannot confirm final usage. |

Startup waits at most ten seconds for ICE and thirty seconds total for `session.started`. A page exit releases resources immediately because browsers cannot guarantee asynchronous finalization while navigating away. Muting playback neither cancels a GitHub operation nor erases audio already heard by other participants. Muted playback continues draining; rapid Stop → Resume can still expose in-flight speech and must be tested. This module sends no undocumented same-session audio-clear/cancel commands. Keep input enabled if the UI needs Live to hear a new wake word; Stop speaking is separate from ending the session.

The only browser HTTP call is `POST /api/live/session` with `{sdp}` and no API key. The backend must return `{session:{id},transport:{type:"webrtc",sdp}}` and select `gpt-live-1` in server configuration. Model selection, credentials, prompting, session policy and tools belong to the backend/UI owners.

## Verification

```sh
node --test tests/browser-audio/*.test.mjs
python3 -B -m unittest discover -s tests/browser-audio -p 'test_serve.py' -v
node --check web/media.js
node --check web/live.js
node --check tests/browser-audio/smoke.js
```

Requires Node 22+ for the dependency-free test harness. Tests cover SDP/channel order, startup gating, muted-by-default output, aborts, timeouts, revoked audio, disconnect recovery, final usage, denied/missing capture, and autoplay recovery. Node may warn about experimental mock timers and detecting ES modules in `.js` files; browser code is loaded with `type="module"`. No shared package settings are changed for these tests.

Before marking the meeting task complete, record browser/macOS versions and verify two real rehearsals: second-device speech reaches Live; Chatty's reply reaches the other device; no self-echo; Stop stays effective during pending work; Resume works; ending/revoking capture releases sharing. These checks remain outstanding.

Sources checked September 12, 2026: [OpenAI Live WebRTC client](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live), [Live lifecycle and graceful close](https://developers.openai.com/api/docs/guides/live-conversations), [MDN display capture](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia), [Google Meet presentation audio](https://support.google.com/meet/answer/9308856).
