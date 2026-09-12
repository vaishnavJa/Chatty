# Chatty meeting audio

Chatty participates with voice as a normal meeting participant. It must not present its page or screen. The earlier presentation-audio demo is superseded by the virtual-microphone route below. Output device selection is implemented and tested with browser fakes; the complete virtual-microphone meeting route still requires a real two-device rehearsal.

## Join with the name Chatty

For the demo, use a **guest participant named Chatty**. Keep Munir's Google profile name unchanged: editing that profile can change the name shown across other Google services.

1. Have a teammate create the Google Meet and provide its link.
2. Open a fresh Chrome Guest window, or an Incognito window that is not signed into Google. Keep the existing signed-in browser session unchanged.
3. Open the meeting link in that window. Enter **Chatty** in the name field and click **Ask to join**. The host or an eligible participant must admit the guest.
4. Join the meeting normally, with the microphone muted until the virtual microphone is configured and camera optional. Do not use **Present** on the pre-join screen: that enters Companion mode, where the microphone and speakers are unavailable.
5. Open the local Chatty app in a second tab of the **same guest/Incognito window**, then follow the audio setup below.
6. Have another participant confirm that the meeting shows **Chatty** before starting the demo.

Guest admission and presentation depend on the host's settings and any organization restrictions. If guest joining is unavailable, use an allowed demo account named Chatty; do not rename Munir's personal profile as a fallback.

References: [Join Meet without a Google Account](https://support.google.com/meet/answer/9303069) and [Google profile name changes](https://support.google.com/accounts/answer/27442). This documents the intended setup; no guest has been admitted or account renamed by this change.

## Route and laptop setup

```text
Teammates → Meet tab audio → Chatty capture → OpenAI Live
Teammates ← Meet microphone ← virtual audio cable ← Chatty Live output
```

Use Chrome on this Mac and localhost or HTTPS for Chatty. Keep Meet and Chatty in the same browser profile. Humans join from other devices, preferably using headphones. The browser capture chooser shares the **incoming Meet tab with Chatty locally**; it does not present anything to meeting participants.

1. Install or identify a working virtual audio cable. A device must actually pass output samples into its corresponding input; being named “virtual” is not sufficient. A standard option is [BlackHole 2ch](https://github.com/ExistentialAudio/BlackHole), installed separately on the Mac. This repository adds no driver dependency and does not install one automatically.
2. In Chatty, refresh audio devices and select the virtual cable as **Chatty's voice output**. If the browser hides device names, use the explicit audio-device permission control. Its temporary microphone stream is stopped immediately and is never sent to Live.
3. In **Meet → Settings → Audio**, select the same virtual cable as the **microphone**, and select **headphones or MacBook speakers** as the **speaker**. Keep the Mac's default/system output on headphones/speakers too. Never route Meet's speaker or system-wide sound to the virtual cable: Chatty would hear and retransmit the meeting.
4. Unmute Meet's microphone only after it is set to the virtual cable. The physical laptop microphone is not part of this route. Keep the camera off if Chatty should have no outgoing video. If an old presentation is active, use **Stop presenting**; do not leave the call.
5. In Chatty select **Meeting tab**, click Start, choose the **Meet tab**, enable **Share tab audio**, and confirm. This chooser is mandatory. The app rejects absent tab audio and known window/screen selections. Do not select the Chatty tab or capture system-wide audio.
6. Use wake/Resume to allow speech. Output starts muted, including while Live connects or an output device changes. If output selection fails, it stays muted; select a valid output explicitly to recover.
7. Have another participant speak. Confirm Chatty hears it and that the other device hears the spoken answer as ordinary participant audio. No Chatty presentation tile should appear.
8. Test Stop, Resume, End, and revoking tab capture. Ending releases capture; Meet remains a separate participant until someone leaves the call.

Do not mute the captured Meet tab itself during the input check; that can affect capture. Use headphones and keep Meet's speaker separate from the virtual cable. If echo or repeated self-transcription appears, stop Chatty's speech immediately and recheck the two device selections.

On this Mac, the existing **Microsoft Teams Audio Device (Virtual)** passed the local cable check on September 12, 2026: a synthetic 440 Hz tone sent through `HTMLAudioElement.setSinkId` was received through the same device's `getUserMedia` input, with peak RMS **0.0564**. Capture was stopped afterward and the meter returned to zero. Use that device as Chatty output and Meet microphone; **no new driver is needed on this laptop**. This proves local cable transport only, not the complete Meet route. Microsoft documents its driver for Teams computer-sound sharing, so repeat the check on other machines rather than assuming compatibility. A separate BlackHole install on another machine may require an administrator password and reopening audio apps; do not change OS security settings or force-close meetings to bypass installation requirements.

Chrome may request macOS screen/audio recording permission for incoming tab capture. Allow the intended browser when prompted, then retry the chooser if needed. Optional incoming screen context is a separate opt-in feature; it does not send a screen or camera feed to Meet participants.

## Backend-independent audio check

Run from the repository root:

```sh
python3 tests/browser-audio/serve.py
```

Open [the local audio harness](http://127.0.0.1:8765/tests/browser-audio/smoke.html) in Chrome. It starts no capture automatically, sends nothing to OpenAI, and writes no recordings. The server binds only to loopback and serves three explicit public assets; it cannot browse the repository or serve credentials.

- Click **Refresh audio devices**. If device labels are hidden, click **Enable device selection** and allow the temporary microphone request. That stream is stopped immediately after device enumeration.
- For a local cable check, choose the cable as **Test tone output**, choose **Microphone (local check)**, then the same cable as **Local input device**. Click Start capture and Play test tone. A peak above silence proves samples crossed the cable locally. Stop capture afterward. This test intentionally loops a synthetic tone; never use this input selection for the real meeting's incoming audio.
- For the real meeting check, select **Meet tab** input and the virtual cable as tone output. Configure Meet's microphone to that cable and its speaker to headphones. The second participant should hear **Play test tone** without any presentation. With other people silent and on headphones, the tone should not move this page's input meter; otherwise the meeting route feeds itself.
- Ask the second-device participant to speak; the input meter should move. Stop/restart capture and revoke tab sharing to verify cleanup and recovery.

These checks isolate audio routing. They do not prove transcription, model response, wake/stop policy, tool execution, or the final end-to-end behavior.

## UI integration contract

Import `captureInput` from `web/media.js` and `connectLive` from `web/live.js` as browser ES modules. No package installation is required. `captureInput("microphone" | "meeting-tab", {keepVideo: false})` returns `{ stream, videoStream, stop }`; call it directly from the Start click, before unrelated asynchronous work. It rejects denied permission, absent audio, and known screen/window selections. By default it removes and stops video tracks immediately. With `{keepVideo:true}` for incoming meeting context it returns retained video in a separate `videoStream`; `stream` remains audio-only, so Live never receives a video track. `capture.stop()`, revoked source capture, and page exit release both. Incoming screen analysis must be explicitly enabled and is documented in [meeting-vision.md](meeting-vision.md).

```js
const cancellation = new AbortController();
const capture = await captureInput("meeting-tab");
const live = await connectLive({
  stream: capture.stream,
  outputDeviceId: selectedOutputDeviceId, // Select the virtual cable before startup.
  signal: cancellation.signal, // Optional: cancel startup or close an active session.
  onEvent: handleLiveEvent,
  onOutputActivity: (active) => updateReplyActivity(active), // Optional local acoustic signal.
  onState: (state, details) => updateConnectionStatus(state, details),
});
// Exposed only after session.started; pass this exact ID to /api/tools/execute.
console.log(live.sessionId);
// Optional later change; output stays muted while routing changes.
await live.setOutputDevice(selectedOutputDeviceId);
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
| `outputDeviceId` | Getter for the audio element's selected output device ID. Empty string means system default. |
| `setOutputDevice(deviceId)` | Selects an already-permitted audio output using `setSinkId`. Serializes changes, mutes while switching, preserves Stop/Resume intent, and rejects unsupported/missing/denied devices. Failure stays silent until an explicit successful selection. It never changes Meet settings. |
| `setOutputMuted(boolean)` | Synchronously changes local playback mute. Returns a playback Promise when retrying unmute. Muting remains effective across late audio tracks; unmute is blocked after close starts. |
| `close()` | Immediately mutes output/disables input. Sends `session.close`, waits up to five seconds for `session.closed`, then releases tracks, playback, channel, and peer. Repeated calls return the same Promise. Resolves `{ finalized, reason, usage?, message? }`. |

`onEvent(event)` receives the original parsed Live event, including transcripts, `response.event`, and final `session.closed`. The UI alone dispatches functions; it must stop submitting new commands once closing starts and ignore stale work from previous sessions. This module does not invent a speech-completed signal or infer voice completion from Responses events.

`onState(state, details)` always includes `details.sessionId` (undefined until the backend answers):

| State | Additional details and meaning |
| --- | --- |
| `connecting` | Startup underway. |
| `ready` | `session.started` received, or a temporary disconnect recovered. |
| `output-device-selected` | `deviceId`: routing succeeded; wake/Resume still controls speech. |
| `output-activity-unavailable` | `message`: acoustic reply detection unavailable; keep manual Stop and the UI wake timeout. |
| `output-device-error` | `message`: routing failed and playback remains muted. Offer device reselection. |
| `playback-blocked` | `message`: UI should offer a Resume click that calls `setOutputMuted(false)`. |
| `reconnecting` | `message`: temporary WebRTC interruption; fail after five seconds if not recovered. |
| `closing` | No new commands; output muted, input disabled. |
| `error` | `message`: startup, transport, or capture failure; render as text. |
| `closed` | `finalized`, `reason`, optional `usage`/`message`. `finalized: true` requires `session.closed`; a socket close or timeout cannot confirm final usage. |

`onOutputActivity(active)` is an optional local acoustic signal, not a Live turn-completed event. It samples only remote output into an analyser every 100 ms and reports RMS above 0.01 while playback is unmuted. It neither records audio nor routes the analyser to speakers. Muting, output switching/failure, and close report inactive. The UI may use a silence interval plus settled tool calls to return to waiting, but silence alone cannot establish semantic response completion. A suspended or unavailable audio context requires manual Stop or a bounded wake timeout.

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

Requires Node 22+ for the dependency-free test harness. Tests cover SDP/channel order, startup gating, muted-by-default output, aborts, timeouts, revoked audio, disconnect recovery, final usage, denied/missing capture, and autoplay recovery. Additional tests cover output selection failures, serialized changes, Stop/close during a pending route, local activity lifecycle, and optional incoming video isolation. Node may warn about experimental mock timers and detecting ES modules in `.js` files; browser code is loaded with `type="module"`. No shared package settings are changed for these tests.

Before marking the meeting task complete, record browser/macOS versions and verify two real rehearsals: second-device speech reaches Live; Chatty's reply reaches the other device; no self-echo; Stop stays effective during pending work; Resume works; ending/revoking capture releases sharing. These checks remain outstanding.

Output permissions: `listAudioOutputs()` returns `{deviceId, label}` for already-exposed outputs without starting capture. `requestAudioOutputs()` must be called from an explicit permission control; it requests a temporary microphone stream to reveal permitted devices, lists outputs, and releases every temporary track even if enumeration fails. Device IDs belong to the browser origin/profile and must not be copied from Meet or another origin.

Sources checked September 12, 2026: [OpenAI Live WebRTC client](https://developers.openai.com/api/docs/guides/voice-webrtc?api=live), [Live lifecycle and graceful close](https://developers.openai.com/api/docs/guides/live-conversations), [MDN display capture](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getDisplayMedia), [audio output selection](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/setSinkId), [local audio levels](https://developer.mozilla.org/en-US/docs/Web/API/AnalyserNode/getFloatTimeDomainData), [device enumeration](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/enumerateDevices), [BlackHole installation](https://github.com/ExistentialAudio/BlackHole), [Microsoft Teams computer audio](https://support.microsoft.com/en-au/teams/meetings/share-sound-from-your-computer-in-microsoft-teams-meetings-or-live-events).
