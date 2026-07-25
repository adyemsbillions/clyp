# Clyp — AI One-Click Video Editor

Clyp is a PHP 8.3 video studio that turns one raw MP4 or MOV file into a polished social-ready edit. It combines Gemini transcription and content generation with a real FFmpeg editing pipeline.

## What the one-click editor does

- Detects long silent sections from the audio waveform and removes dead air
- Maps filler words such as “um”, “uh”, “erm”, “you know” and “I mean” to their timestamps and cuts them
- Measures footage brightness and saturation before applying corrective colour grading
- Rebuilds the timeline with short automatic transitions
- Creates subtle digital punch-ins and reframed cutaways from the source footage
- Selects a matching licensed sound from the local library
- Ducks music beneath speech and raises it during quieter sections
- Normalises voice loudness and limits the final mix
- Burns premium animated captions with word-by-word highlighting
- Generates hooks, platform posts, hashtags and a title
- Exports H.264/AAC MP4 with fast-start playback

The current “smart cutaway” feature reframes and punches into the uploaded footage. It does not fetch third-party B-roll or generate external footage.

## Caption designs

- Impact
- Clean Pro
- Executive
- Bold Glow
- Smart Box
- Pop Bounce

Every design uses animated word highlighting in the exported video.

## Requirements

- PHP 8.3+ with PDO, cURL, fileinfo and mbstring
- FFmpeg and FFprobe available in PATH
- FFmpeg filters: `ass`, `xfade`, `sidechaincompress`, `silencedetect`, `signalstats`
- SQLite for local use or MySQL 8+ for production
- Gemini API key for transcription and social content

## Windows quick start

From PowerShell:

```powershell
cd C:\Users\adyem\Desktop\clyp
.\setup.bat
.\configure-gemini.bat
.\test-gemini.bat
.\start.bat
```

Open `http://localhost:8000`.

PowerShell requires the `./` or `.\` prefix for files in the current directory. The included Python commands use `py`, not `python`.

## One-click workflow

1. Upload a video.
2. Generate captions with Gemini.
3. Open **Auto edit**.
4. Choose an editing rhythm and colour direction.
5. Keep or disable silence cutting, filler removal, punch-ins, transitions and automatic music.
6. Click **Create one-click edit**.
7. Review the plan summary, caption design and soundtrack.
8. Open **Export** and click **Render polished video**.

## Gemini configuration

The default model is:

```env
GEMINI_MODEL=gemini-3.5-flash
```

Configure the key using:

```powershell
.\configure-gemini.bat
```

Clyp extracts mono 16 kHz MP3 audio in fixed ten-minute chunks. The Windows build does not use FFmpeg percent-based segment filename templates.

## Local database

SQLite works without MySQL:

```env
DB_DRIVER=sqlite
DB_SQLITE_PATH=storage/clyp.sqlite
```

Clyp creates and upgrades missing tables and columns automatically. To run the installer manually:

```powershell
php .\scripts\install.php
```

## MySQL production configuration

```env
DB_DRIVER=mysql
DB_HOST=127.0.0.1
DB_PORT=3306
DB_DATABASE=clyp
DB_USERNAME=root
DB_PASSWORD=your_password
```

Then run:

```powershell
php .\scripts\install.php
```

## Auto-editor tuning

```env
AUTO_SILENCE_DB=-34
AUTO_SILENCE_MIN=0.48
```

Lower `AUTO_SILENCE_DB` to require quieter audio before a section is treated as silence. Increase `AUTO_SILENCE_MIN` to preserve longer pauses.

## Verify the installation

```powershell
php .\scripts\check.php
```

The checker validates PHP extensions, storage permissions, FFmpeg, FFprobe and all filters required by the automatic editor.

## Storage and payments

Local storage works immediately. Cloudflare R2 mirroring and Paystack subscription verification remain optional and are configured through `.env`.

## Production notes

- Point the server document root to `/public`.
- Use HTTPS, MySQL and `APP_DEBUG=false`.
- Run rendering through background workers for production traffic.
- Keep uploaded videos and API keys private.
- Only distribute music and footage for which you have the required rights.
