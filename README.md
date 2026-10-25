# Clyp — Design Studio + Video Editor

Clyp has two main features:

1. **Design studio** — AI-art-directed, editable flyers and posters (`app.html`, `editor.html`).
2. **Video editor** — captions, background sound and colour grading, exported as MP4 (`video.html`).

The home page (`index.html`) links to both.

This build keeps the fast local development architecture:

- Browser UI on `http://127.0.0.1:8080`
- Python web proxy
- Python AI service on `http://127.0.0.1:8100`
- Gemini design reasoning
- Browser `localStorage` for projects
- No registration/login gate
- No MySQL/XAMPP dependency in the active workflow

## Start

On the Windows machine used for this project:

```powershell
py -m pip install -r requirements.txt
py start_local.py
```

The video editor also needs FFmpeg. Put it on `PATH` or set `CLYP_FFMPEG_PATH` / `CLYP_FFPROBE_PATH` in `.env`.
Gemini reads `CLYP_GEMINI_API_KEY`, or `GEMINI_API_KEY` from the older PHP build's `.env`.

Leave that terminal open and visit `http://127.0.0.1:8080`.

## What is new in Design Intelligence V3

### Clyp design brain

`design_intelligence.py` is now a first-class product asset. It gives Gemini a professional art-direction playbook covering:

- single-message communication
- three-level hierarchy
- grid/alignment/proximity
- negative space and balance
- typography pairing and sizing
- colour harmony and palette restraint
- contrast/readability
- RGB versus print/CMYK awareness
- gradients
- imagery and text-on-photo treatment
- purposeful shapes and graphic elements
- shadows, strokes and effects
- category-specific art direction
- failure modes Clyp should avoid
- an internal pre-output design QA sequence

The AI is not being fine-tuned at the model-weight level. Clyp is improving it through a strong system instruction, few-shot art-direction patterns, a richer editable design vocabulary, Python validation and a local quality audit.

### Advanced editable primitives

Clyp can now render AI-created:

- rectangles
- ellipses/circles
- pills/badges
- lines/dividers
- triangles/wedges
- solid fills
- linear gradients
- borders/strokes
- soft shadows
- text shadows
- text outlines
- image brightness/contrast/saturation/blur

These remain structured editable layers.

### Better colour handling

The design planner now chooses a named harmony strategy:

- monochromatic
- analogous
- complementary
- split-complementary
- triadic

It also returns dominant/support/accent/light/dark palette roles. Python preserves this palette metadata and calculates a lightweight quality summary including font-family count, colour count, tiny text and conservative contrast checks.

### Better manual Elements panel

The editor now exposes professional primitives directly:

- Rectangle
- Circle
- Pill
- Line
- Gradient
- Triangle
- Frame
- Readability Overlay

The Properties panel exposes fill type, second gradient colour, gradient angle, border and shadow controls where relevant.

### Typography

The editor can use these web/display faces when online, with system fallbacks when unavailable:

- Inter
- Manrope
- Bebas Neue
- Oswald
- Playfair Display

Clyp is instructed to use no more than two font families in normal flyer work unless a third tiny decorative accent is genuinely justified.

## Reconstruction remains trace-first

Reconstruction V2 behaviour is preserved:

- source aspect ratio is preserved
- complex source photography/logos/icons/effects can stay as image crop layers
- editable text stays editable
- simple geometry stays editable
- source matching is prioritised over redesign

## Current deliberate limitation

From-scratch AI design can art-direct professional layouts, colour, type and graphic primitives, but automatic generation of a new hero photograph/illustration is not yet turned on in this patch. That should be a separate image-asset generation step so Clyp can place the resulting asset as an editable/croppable image layer rather than flattening the entire flyer.

This separation is intentional: **design planning and image synthesis are different jobs**.


## V4.1 — mandatory imagery fix
When the user's brief explicitly asks for photography, people, a model, illustration, or another hero visual, Clyp now treats the image as mandatory. The design endpoint will automatically generate and insert a full-bleed hero asset even if the layout planner forgets to return an image layer. If the image model fails, the request fails with the actual image error instead of silently returning a plain typography-only flyer.


## Video editor

`video_service.py` adds the video editor to the web service. Projects are stored on disk in `storage/video/<id>/`, because videos are too large for browser storage.

- **Captions.** *Generate captions with AI* extracts the audio with FFmpeg and sends it to Gemini (`/transcribe` in `ai_service.py`). The transcript is split into short lines that you can edit. The default **Signature** style shows words one at a time as they're spoken, left-aligned in the lower third. The key word in each line is bigger and heavier, and you can choose it by wrapping it in `*asterisks*`. Six karaoke-style presets (Viral, Professional, and others) are also included.
- **Sounds.** Pick a library track from `storage/sounds/` or upload your own to `storage/sounds/uploads/`. You can set the music volume, the original audio level and the start offset, and lower the music automatically while people talk.
- **Colour grading.** Choose a preset (Vivid, Warm, Cool, Cinematic, Vintage, Moody, Black & white), then adjust brightness, contrast, saturation, temperature, tint and vignette. The player shows a fast live preview, and *Check exact frame* renders one frame through FFmpeg exactly as the export will look.
- **Export.** Renders to an H.264/AAC MP4 in the background with a progress bar, then offers it for download.

The older PHP auto-editor in `app/` and `public/` is no longer used.
