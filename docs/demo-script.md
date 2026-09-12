# Chatty: quick live demo

Run `uv run chatty` from the repository and open <http://localhost:3000> in Chrome. The local server must have `OPENAI_API_KEY` configured and GitHub CLI access to `vaishnavJa/Chatty`. The browser never receives either credential.

## Two-minute microphone test

1. Leave **Microphone · quick test** selected and click **Start session**. Allow microphone access. Wait for **Connected to Live**; the UI does not mark a session connected before Live starts.
2. Ask: “What are the latest three commits in the Chatty repository?” Look for your words and Chatty’s response under **Conversation**, and the returned GitHub sources under **Actions & sources**.
3. Ask: “Create an issue titled ‘Demo: save meeting summaries’ with a description explaining that summaries should include decisions and owners.” Review the actual title and body in the action card, then click **Create issue** once. A successful action must show the returned GitHub URL. **Reject** creates nothing.
4. While Chatty answers, say “Chatty, stop,” or click **Stop speaking**. Replies mute locally; input stays on. Say “Hey Chatty” or click **Resume** to permit replies again.
5. Click **Summarize**. The UI waits for Live to accept the summary instruction, then prompts it to speak. Only actual Live output appears as the summary; a backend completion does not mean it was spoken or heard.
6. Click **Transcript** to download the actual captured fragments and source links. Click **End session** to stop capture and close Live.

If browser playback is blocked, click **Resume**. If creation reports an uncertain result, inspect the repository before making another request: an issue may already exist.

## Google Meet test

1. Join a Meet call on this laptop; have another participant join from a second device.
2. In Chatty, select **Meeting tab · Google Meet**, then **Start session**. Select the Meet browser tab and check **Share tab audio**.
3. In Meet, present the Chatty browser tab with tab audio enabled. This carries Chatty’s voice back to participants. Keep the Meet microphone muted on this laptop to prevent an acoustic echo.
4. Ask the other participant to say “Hey Chatty, what changed in our repository?” Meeting mode starts with replies muted and wakes from the detected input phrase.
5. Verify both directions of audio with the other participant. Seeing captions alone does not prove they heard Chatty.

The tab chooser always requires a user gesture. Canceling it or ending during startup stops any subsequently returned capture. Choosing a window or a tab without audio yields a real error.

## Verification and limits

Run the dependency-free event controller tests with:

```sh
node --test tests/demo-ui/*.test.mjs
```

The controller covers nested GPT-Live Responses delegation, duplicate call IDs, all-results-before-continuation, user-approved writes, wake/stop across transcript fragments, stopped work, ended sessions, uncertain writes, and GitHub-only source links.

Wake/stop detection depends on transcript delivery and is not a local wake-word engine. The **Stop speaking** button mutes immediately. Resume permits the current remote audio stream; it does not guarantee stale audio has been flushed. Caption rows use approximate time grouping, while original text fragments and intervals remain in memory. The page does not persist conversation state after reload. Meeting participation and audio return still need verification in a real call.

The UI is the sole data-channel tool dispatcher; adding a second sideband executor would require coordination to avoid duplicate actions. GitHub writes are approved in the UI and checked again by the backend.

Event references: [Live delegation](https://developers.openai.com/api/docs/guides/live-delegation), [Live sessions and captions](https://developers.openai.com/api/docs/guides/live-conversations), [Server controls](https://developers.openai.com/api/docs/guides/voice-server-controls?api=live).
