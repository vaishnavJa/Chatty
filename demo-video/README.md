# Chatty demo video

An English, 10-second Remotion intro followed by your real meeting recording.
Output: 1920 × 1080, 30 fps, H.264 MP4 with audio.

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
