# Chatty demo video

Two separate edits: a narrated 60-second Chatty advertisement, and the original 10-second intro followed by your real meeting recording. Both export at 1920 × 1080, 30 fps, H.264 MP4 with audio. The existing **ChattyIntro** and **ChattyDemo** compositions are preserved.

## The one-minute advertisement

```sh
cd demo-video
npm ci
npm run render:ad
npm run poster:ad
```

Select **ChattyAd60** in Studio. It is exactly **1,800 frames / 60 seconds**. The finished video is `out/chatty-ad-60s.mp4`, with the poster at `out/chatty-ad-poster.png`. It includes an English AI-generated voice, original instrumental music, and open captions. `out/chatty-ad-60s.srt` and `out/chatty-ad-script.txt` are the companion caption and narration files produced by the audio script.

The advertisement export requires `ffmpeg` and `ffprobe` on the PATH in addition to the existing Node dependencies. The finalization step copies the H.264 frames without re-encoding, replaces encoder-padded audio with the exact-duration mix, and verifies a 60.000-second MP4 with 1,800 frames. The container is prepared for streaming with fast-start metadata. No meeting capture is used by this command.

| Time | Story | Visual |
| --- | --- | --- |
| 0:00–0:06 | The answers are somewhere else | A meeting discussion about a login bug |
| 0:06–0:13 | Meet Chatty | Fictional participant tiles and Chatty's voice |
| 0:13–0:21 | Bring project context into the conversation | Example commit, pull request and issue source cards |
| 0:21–0:29 | Keep talking | A request to draft an issue and a question about its title |
| 0:29–0:38 | Refine the draft | Change the title, then hear a brief approval summary |
| 0:38–0:45 | Turn agreement into action | Natural consent and a visibly illustrative issue result |
| 0:45–0:52 | Stay in control | “Chatty, stop.” / “Okay.” / Quiet listening |
| 0:52–1:00 | From conversation to action | Chatty brand and repository call to action |

This advertisement is **an illustrative product animation, not a recording or proof of live reliability**. Product scenes visibly say “Illustrative workflow · Fictional example.” Alex, Maya and Sam are fictional. The example GitHub content, draft, dialogue and issue result are editorial illustrations: no issue number, actual receipt or real customer information is fabricated. The ad does not claim working Microsoft Teams data access, Jira support or automatic joining of meeting platforms. A real meeting rehearsal is separate evidence.

The AI-generated narration is disclosed on the final card. OpenAI's built-in `marin` voice was generated with `gpt-4o-mini-tts`; it does not impersonate a person. The bundled final mix can be rendered without any API key. The accompanying music and transition sounds are original, deterministic synthesis in `scripts/create-ad-audio.mjs`, without third-party recordings or samples. The mark follows the existing Chatty mark used in this repository, and Geist uses the bundled SIL Open Font License.

To revise the narration, edit `src/ad-script.json`, then run:

```sh
npm run sound:ad
npm run render:ad
```

`sound:ad` uses `OPENAI_API_KEY` from the process environment or the repository's ignored `.env` file. It sends only the public narration text to the [OpenAI speech endpoint](https://developers.openai.com/api/docs/guides/text-to-speech), never the contents of that file. It does not log the key or put it in command arguments. This command generates paid API audio; normal rendering uses the already bundled mix and makes no speech requests. Cached individual voice takes are in ignored `out/ad-audio/`; remove the affected take there when changing a line. The script measures each take, gently fits it only when needed, and writes the exact caption intervals to `src/ad-timings.json`. It refuses a take requiring more than 22% acceleration so narration is not silently rushed. The final mix is 48 kHz stereo, targeted at −16 LUFS with a −1.5 dBTP ceiling.

Visual source: `src/ChattyAd60.tsx`. Set `captions: false` or `sound: false` in composition props for alternative exports. Stills and rendered exports remain ignored by Git; source, timing data, and the final generated sound mix are versioned.

## Preview and export

```sh
cd demo-video
npm ci
npm run dev
npm run render:intro
```

Select **ChattyIntro** in Studio. The export is `out/chatty-intro.mp4`.
All animations use the Remotion frame clock. Fonts and sound are local.

## Add the meeting recording

```sh
npm run render:demo -- "C:/recordings/meeting.mp4"
```

To use only seconds 12–92 of the source recording:

```sh
npm run render:demo -- "C:/recordings/meeting.mp4" 12 92
```

This copies the recording to `public/meeting/`, writes `meeting.props.json`, and exports `out/chatty-demo.mp4`. The original is untouched. Recording copies, props, and exports are ignored by Git. Run `npm run render:demo` again to reuse the saved edit.

To prepare the edit without rendering:

```sh
npm run prepare:meeting -- "C:/recordings/meeting.mp4" 12 92
npx remotion studio --props=meeting.props.json
```

Select **ChattyDemo**. Its duration is calculated from the recording and trim. Without a recording, Studio previews the intro; a full-demo export fails with an explicit instruction instead of exporting an incomplete demo.

The recording begins at **00:10.000**, including its original audio from the selected start point. The intro sound ends before the handoff. Video fits inside the frame without cropping screen content; other aspect ratios have borders. Trim points snap to 30 fps frames.

## The ten-second story

| Time | Picture | Copy |
| --- | --- | --- |
| 0:00–0:03 | Warm paper, conversation bubbles, moving voice bars | **Your team is talking.** / “What changed?” / “What’s next?” |
| 0:03–0:06.7 | Charcoal, GitHub source labels arriving in sequence | **Your project. In the conversation.** / Commits / Pull requests / Issues |
| 0:06.7–0:10 | Orange title reveal, fade into the recording | **Meet Chatty.** / Keep the conversation moving. / Let’s join the meeting |

Voice bars and questions are editorial motion graphics, not recorded product output. The intro presents the intended demo story. It does not demonstrate a working meeting integration by itself. This checkout contains GitHub tools; the end-to-end meeting experience must be shown in the actual recording.

## Suggested recording cut

Begin just before the first useful question. Show Chatty answering a real project question, then show the source in GitHub. If the recording includes an explicitly requested issue creation, keep the request, response, and actual resulting issue together. Remove setup delays and repeated attempts between complete exchanges; retain the real response time within each exchange. End after the result is visible and the sentence finishes.

## Editing

- Wording, colors, mark and motion: `src/Intro.tsx`.
- Recording playback and duration: `src/Meeting.tsx`.
- Composition settings: `src/Root.tsx`.
- Original sound generator: `scripts/create-sound.mjs`; regenerate with `npm run sound`.
- Silent intro: set `sound` to `false` in `ChattyIntro` default props.

The Chatty mark is a provisional graphic for this edit, not a supplied official logo. Geist is bundled under the SIL Open Font License in `public/fonts/OFL-geist.txt`. The sound is synthesized for this intro; there is no third-party music or voiceover.

## Checks

```sh
npm run lint
npm run render:intro
```

The configuration uses Webpack because the scaffold's Rspack path failed to produce a usable bundle on the Windows host. Remotion packages are pinned to the same version. Mediabunny matches the Remotion media dependency.
