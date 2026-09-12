# Chatty landing page

A static landing page inspired by the supplied AXIOM reference. Open `dist/index.html` through a local HTTP server:

```sh
uv run python -m http.server 4173 --directory landing/dist --bind 127.0.0.1
```

On desktop and tablet (768px and wider), the first section keeps the original full-width video above the headline. On phones, it leads with the Chatty logo and headline, followed by an edge-to-edge video with compact spacing below. The original ten-second intro from [PR #16](https://github.com/vaishnavJa/Chatty/pull/16) preserves its full 16:9 frame. It autoplays muted and loops, without a frame, caption, or playback controls; the device's reduced-motion preference pauses the animation. Playback resumes when returning to the page, subject to browser autoplay policy. The MP4 and poster were rendered from the repository's `demo-video` source; this is an introduction, not a meeting recording.

The Chatty SVG marks reproduce the video source's `Mark` component. Geist and its bundled OFL licence are included locally. The palette follows the video: ink `#111512`, paper `#f1f0e8`, orange `#ff7146`. Small orange text on paper uses a darker shade for readability.

The footer uses the unmodified blue AI Tinkerers wordmark from its [official website](https://aitinkerers.org/), linking back to that site. Source asset: https://images.aitinkerers.org/ai_tinkerers/logos/ai-tinkerers-transparent-extra-large.png.

The page has no signup backend or invented availability claims. Its project action links to GitHub. All site assets live in `dist`; `.openai/hosting.json` identifies the private Sites deployment.

## Vercel

Deploy only this `landing` directory. `vercel.json` selects the static `dist`
output with no dependency installation or build step. No environment variables
or backend services are required.

For a Git import, set **Root Directory** to `landing` and **Framework Preset**
to **Other**. Commit `landing/dist` along with the configuration; the local
`.gitignore` makes these source assets visible despite the parent Python ignore
rule. Keep “Include source files outside of the Root Directory” disabled.

For a CLI deployment from the repository root:

```sh
vercel login
vercel link --cwd landing --scope ronly2460s-projects
vercel deploy --cwd landing --scope ronly2460s-projects
```

After reviewing the preview, publish with:

```sh
vercel deploy --cwd landing --scope ronly2460s-projects --prod
```

`.vercelignore` excludes Sites metadata and this README from the upload. Purchase
a domain only after checking its registration and renewal prices, then attach it
to this Vercel project under Settings → Domains.
