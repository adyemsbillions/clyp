# Upgrade an existing Clyp installation to Gemini

1. Stop the running PHP server with `Ctrl+C`.
2. Copy the patch files into the root of your existing Clyp folder and allow Windows to replace matching files.
3. Keep your existing `storage/clyp.sqlite`, uploads, exports and `.env` file.
4. Run:

```powershell
.\configure-gemini.bat
.\test-gemini.bat
.\start.bat
```

The configurator asks for the key privately and updates `.env` with:

```env
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-3.5-flash
GEMINI_LANGUAGE=auto
GEMINI_API_BASE=https://generativelanguage.googleapis.com/v1beta
```

Open the existing project and press **Generate with AI** again. Failed temporary audio chunks are cleared automatically before a new transcription attempt.
