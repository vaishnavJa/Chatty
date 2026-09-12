# Chatty: quick live demo

Run `uv run chatty` from the repository and open <http://localhost:3000> in Chrome. The local server must have `OPENAI_API_KEY` configured and GitHub CLI access to `vaishnavJa/Chatty`. The browser never receives either credential.

## Two-minute microphone test

1. Leave **Microphone · quick test** selected and click **Start session**. Allow microphone access. Wait for **Connected to Live**; the UI does not mark a session connected before Live starts.
2. Ask: “Chatty, what are the latest three commits in the Chatty repository?” Look for your words and Chatty’s response under **Conversation**, and the returned GitHub sources under **Actions & sources**.
3. Ask: “Chatty, create an issue titled ‘Demo: save meeting summaries’ with body ‘Include decisions and owners.’” Listen to its saved proposal and “Do you approve this change?” Then say **Yes** or **Chatty confirm**. No approval click is needed. A successful action must show the returned GitHub URL. For another proposed change, say **No** or **Chatty cancel** and verify that nothing is written.
4. While Chatty answers, say “Chatty, stop,” or click **Stop speaking**. Replies mute locally; input stays on. Say “Hey Chatty” or click **Resume** to permit replies again.
5. Click **Summarize**. The UI waits for Live to accept the summary instruction, then prompts it to speak. Only actual Live output appears as the summary; a backend completion does not mean it was spoken or heard.
6. Click **Transcript** to download the actual captured fragments and source links. Click **End session** to stop capture and close Live.

If browser playback is blocked, click **Resume**. If creation reports an uncertain result, inspect the repository before making another request: an issue may already exist.

## Google Meet test

1. Join a Meet call on this laptop; have another participant join from a second device. Use the [voice-only setup](meeting-setup.md) and keep Chatty's outgoing screen presentation off.
2. Select the configured virtual audio device as **Chatty's voice output**. In Meet, select the corresponding virtual microphone and keep it **on**. Meet's speaker must use a different device, so incoming participants are not fed straight back into the meeting.
3. In Chatty, select **Meeting tab · Google Meet**, then **Start session**. Select the Meet browser tab and check **Share tab audio**. This captures incoming audio locally for Chatty; it does not present anything to the meeting.
4. Ask the other participant to say “Hey Chatty, what changed in our repository?” Meeting mode starts with replies muted and wakes from the detected input phrase.
5. Verify both directions of audio with the other participant. Seeing captions alone does not prove they heard Chatty. Repeat the spoken issue proposal and approval from that participant's device, then verify one actual issue link.

The tab chooser always requires a user gesture. Canceling it or ending during startup stops any subsequently returned capture. Choosing a window or a tab without audio yields a real error.

## Verification and limits

Run the dependency-free event controller tests with:

```sh
node --test tests/demo-ui/*.test.mjs
```

The controller covers nested GPT-Live Responses delegation, duplicate call IDs, all-results-before-continuation, spoken approval, wake/stop across transcript fragments, stopped work, ended sessions, uncertain writes, and GitHub-only source links.

Wake/stop detection depends on transcript delivery and is not a local wake-word engine. The **Stop speaking** button mutes immediately. Resume permits the current remote audio stream; it does not guarantee stale audio has been flushed. Caption rows use approximate time grouping, while original text fragments and intervals remain in memory. The page does not persist conversation state after reload. Meeting participation and audio return still need verification in a real call.

The UI is the sole data-channel tool dispatcher; adding a second sideband executor would require coordination to avoid duplicate actions. GitHub writes require [spoken confirmation of a saved proposal](voice-approval.md), checked by the backend. The local browser relays transcript and audio-activity evidence; this does not authenticate speakers. Input quiet and settled captions estimate the answer boundary and require a real meeting rehearsal.

Event references: [Live delegation](https://developers.openai.com/api/docs/guides/live-delegation), [Live sessions and captions](https://developers.openai.com/api/docs/guides/live-conversations), [Server controls](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live).
