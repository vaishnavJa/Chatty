# Chatty demo video

Two separate edits: a narrated 60-second Chatty advertisement, and the 10-second intro followed by your real meeting recording. Both export at 1920 × 1080, 30 fps, H.264 MP4 with audio. **ChattyIntro** and **ChattyDemo** keep their existing structure; both the intro and advertisement now use the supplied Chatty mascot through `src/BrandMark.tsx`.

## The one-minute advertisement

```sh
cd demo-video
npm ci
npm run render:ad
npm run poster:ad
```

Select **ChattyAd60** in Studio. It is exactly **1,800 frames / 60 seconds**. The finished video is `out/chatty-ad-60s.mp4`, with the poster at `out/chatty-ad-poster.png`. It includes English neural narration, original instrumental music, and open captions. `out/chatty-ad-60s.srt` and `out/chatty-ad-script.txt` are the companion caption and narration files produced by the audio script. The delivered voice revision also has versioned `-v3` filenames. Previous local deliverables are preserved in ignored `out/previous-v1/` and `out/previous-v2/`.

The advertisement export requires `ffmpeg` and `ffprobe` on the PATH in addition to the existing Node dependencies. The finalization step copies the H.264 frames without re-encoding, replaces encoder-padded audio with the exact-duration mix, and verifies a 60.000-second MP4 with 1,800 frames. The container is prepared for streaming with fast-start metadata. No meeting capture is used by this command.

| Time | Story | Visual |
| --- | --- | --- |
| 0:00–0:06 | The answers are somewhere else | A meeting discussion about a login bug |
| 0:06–0:13 | Meet Chatty | The supplied mascot in a meeting with fictional participants; built for ticketing and work systems |
| 0:13–0:21 | Your tools. Your data. One conversation. | Read, understand and act with a supported connection and permission; **Current demo: GitHub / More connectors planned** |
| 0:21–0:29 | Keep talking | A request to draft a ticket and a question about its title |
| 0:29–0:38 | Refine the draft | Change the title, then hear a brief approval summary |
| 0:38–0:45 | Turn agreement into action | Natural consent and a visibly illustrative GitHub issue example |
| 0:45–0:52 | Stay in control | “Chatty, stop.” / “Okay.” / Quiet listening |
| 0:52–1:00 | From conversation to action | Large supplied mascot, connected-work positioning and repository call to action |

This advertisement is **an illustrative product animation, not a recording or proof of live reliability**. Product scenes visibly say “Illustrative workflow · Fictional example.” Alex, Maya and Sam are fictional. The draft, dialogue and GitHub issue result are editorial illustrations: no issue number, actual receipt or real customer information is fabricated. The positioning covers connected ticketing and work systems, conditional on a supported connector and the user's authorization. **GitHub is the implemented connector shown in this demo; further connectors are planned.** The ad does not claim working Microsoft Teams data access, Jira support or automatic joining of meeting platforms. A real meeting rehearsal is separate evidence.

The synthetic narration is disclosed on the final card. This revision uses **Kokoro-82M v1.0 with the stock American English `af_heart` neural voice for all eight scenes**. All takes were generated locally at the same synthesis setting (1.05), with no voice cloning or post-generation speed-up. The narrator engine changed from the previous macOS Samantha edit; the approved words, mascot, visual scenes, music and total duration remain the same. The bundled final mix renders without an API key or a voice model installed in the repository.

Generation used the full-precision ONNX model through `kokoro-onnx` 0.6.1 in a separate temporary environment. The [Kokoro model](https://huggingface.co/hexgrad/Kokoro-82M) is Apache-2.0, and the [ONNX implementation](https://github.com/thewh1teagle/kokoro-onnx) is MIT-licensed. The model and [stock voice information](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md) are recorded with model/take hashes in `src/ad-voice.json`. Model weights, Python environments and caches are not included in this repository. The accompanying music and transition sounds are original, deterministic synthesis in `scripts/create-ad-audio.mjs`, without third-party recordings or samples. Geist uses the bundled SIL Open Font License.

The supplied Chatty logo is copied unchanged to `public/brand/chatty-mascot.png` (1,254 × 1,254 RGBA; SHA-256 `760f46e1882a6dea1908740e2b90530e1bbc00a555ae5a14490e251ab969a2bf`). Its pixels and transparency are preserved; sizing, positioning and light backplates are layout only. `src/BrandMark.tsx` is shared by the advertisement and intro. No third-party vendor marks imply unavailable integrations.

To revise the narration, edit `src/ad-script.json` and synthesize eight complete WAV takes with the same narrator. Import them with:

```sh
npm run sound:ad -- --takes-dir /absolute/path/to/narration-takes
npm run render:ad
```

The directory must contain `narration-01.wav` through `narration-08.wav` and `manifest.json`. The manifest needs nonempty `model`, `voice`, `license` and `source` strings, plus a `takes` array with exactly one entry per scene. Each entry contains `id` (`"01"`–`"08"`), `file` (`"narration-01.wav"`, etc.) and `text` exactly matching the corresponding script paragraph. An optional `sha256` is verified. Optional numeric `speed` records the synthesis setting. The importer checks every file, script match, duration and supplied hash before changing outputs, and then copies takes into ignored `out/ad-audio-imported/` so an older cache cannot substitute stale words.

**Imported narration is never sped up or cut.** Each full take must fit its scene with 0.30 seconds of lead-in and at least 0.35 seconds of trailing room. If necessary, adjust the synthesis delivery or rebalance scene durations while keeping the full composition at 60 seconds. The pipeline applies loudness normalization, mixes the original score, and pads the timeline. Public provenance contains only selected model/voice/license URLs, speeds and hashes; scratch paths are excluded.

Legacy voice generation is still available explicitly: `--local-voice` uses macOS Samantha and makes no network requests; its cache is ignored `out/ad-audio-local/`. Omitting both options uses OpenAI's `marin` voice and generates paid API audio. That path reads `OPENAI_API_KEY` from the process environment or the repository's ignored `.env`, sends only public narration text to the [OpenAI speech endpoint](https://developers.openai.com/api/docs/guides/text-to-speech), and caches audio in ignored `out/ad-audio/`. It never logs the key or puts it in command arguments. Remove the affected legacy cached take before changing its text. Normal rendering always uses the bundled mix and makes no speech requests.

The script measures each take and writes its caption interval to `src/ad-timings.json`. Only the legacy generation paths retain their bounded timing adjustment; the imported neural takes use their original synthesized pace. The final mix is 48 kHz stereo, targeted at −16 LUFS with a −1.5 dBTP ceiling.

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

The intro uses the supplied Chatty mascot through `src/BrandMark.tsx`. Geist is bundled under the SIL Open Font License in `public/fonts/OFL-geist.txt`. The sound is synthesized for this intro; there is no third-party music or voiceover in the intro itself.

## Checks

```sh
npm run lint
npm run render:intro
```

The configuration uses Webpack because the scaffold's Rspack path failed to produce a usable bundle on the Windows host. Remotion packages are pinned to the same version. Mediabunny matches the Remotion media dependency.
