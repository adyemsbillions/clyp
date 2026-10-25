"""Clyp video editor: captions, background sound and colour grading on top of FFmpeg.

Registered as a blueprint on the web service. Video projects live on disk under
storage/video/<id>/ because source videos are far too large for browser storage.
"""
from __future__ import annotations

import base64
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, request, send_file
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
VIDEO_ROOT = ROOT / "storage" / "video"
SOUND_ROOT = ROOT / "storage" / "sounds"
SOUND_UPLOADS = SOUND_ROOT / "uploads"
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
SOUND_EXTS = {".wav", ".mp3", ".m4a", ".aac", ".ogg"}
PROJECT_ID = re.compile(r"^[a-f0-9]{12}$")

video = Blueprint("video", __name__)
_lock = threading.Lock()
_sound_cache: dict[str, tuple[float, float]] = {}


# ---------------------------------------------------------------------------
# Style catalogues. The browser preview reads these through /api/video/options
# so the live overlay and the FFmpeg export share one definition.
# ---------------------------------------------------------------------------

# size/outline/shadow are in pixels for a 1080-wide portrait frame and scale with the video.
# kind "build": words appear one by one as spoken and stay up for the phrase; *starred* words
# are emphasised (bigger, heavier). kind "karaoke": the whole phrase shows and fills word by word.
CAPTION_STYLES: dict[str, dict[str, Any]] = {
    "signature": {"label": "Signature", "kind": "build", "align": "left", "font": "Segoe UI Semibold", "emphasis_font": "Segoe UI Black", "emphasis_scale": 1.45, "size": 106, "spacing": -1.5,
                  "base": "#FFFFFF", "highlight": "#FFFFFF", "outline": "#000000", "outline_size": 0, "box": False, "back": "#000000", "back_alpha": 0.6, "shadow": 0, "upper": False},
    "viral": {"kind": "karaoke", "align": "center", "label": "Viral", "font": "Impact", "size": 72, "base": "#FFFFFF", "highlight": "#FFE800", "outline": "#000000", "outline_size": 5, "box": False, "back": "#000000", "back_alpha": 0.66, "shadow": 2, "upper": True},
    "professional": {"kind": "karaoke", "align": "center", "label": "Professional", "font": "Segoe UI Semibold", "size": 52, "base": "#D8D8D8", "highlight": "#FFFFFF", "outline": "#272A30", "outline_size": 1, "box": True, "back": "#171717", "back_alpha": 0.6, "shadow": 0, "upper": False},
    "business": {"kind": "karaoke", "align": "center", "label": "Business", "font": "Arial", "size": 54, "base": "#FFFFFF", "highlight": "#DDF3FF", "outline": "#102E54", "outline_size": 2, "box": True, "back": "#0F172A", "back_alpha": 0.53, "shadow": 0, "upper": False},
    "motivational": {"kind": "karaoke", "align": "center", "label": "Motivational", "font": "Arial Black", "size": 64, "base": "#FFFFFF", "highlight": "#FFE500", "outline": "#2F0C19", "outline_size": 5, "box": False, "back": "#000000", "back_alpha": 0.68, "shadow": 2, "upper": True},
    "educational": {"kind": "karaoke", "align": "center", "label": "Educational", "font": "Segoe UI Semibold", "size": 50, "base": "#FFF7E6", "highlight": "#FFFFFF", "outline": "#163B68", "outline_size": 1, "box": True, "back": "#12264E", "back_alpha": 0.27, "shadow": 0, "upper": False},
    "comedy": {"kind": "karaoke", "align": "center", "label": "Comedy", "font": "Arial Black", "size": 66, "base": "#FFFFFF", "highlight": "#FFF765", "outline": "#370B42", "outline_size": 5, "box": False, "back": "#000000", "back_alpha": 0.68, "shadow": 3, "upper": True},
}

GRADE_KEYS = ("brightness", "contrast", "saturation", "temperature", "tint", "vignette", "grain")

# Looks are applied on top of the automatic correction and scaled by the look strength.
# values use the -100..100 slider scale; balance is FFmpeg colorbalance (s/m/h = shadows,
# midtones, highlights); fade lifts the blacks (0..0.15) for a matte/film finish.
GRADE_PRESETS: dict[str, dict[str, Any]] = {
    "none": {"label": "Original", "values": {}},
    "pro": {"label": "Clyp Pro", "values": {"contrast": 12, "saturation": 8, "temperature": 6, "vignette": 18},
            "balance": {"rs": -0.03, "bs": 0.04, "rh": 0.03, "bh": -0.03}},
    "teal_orange": {"label": "Teal & Orange", "values": {"contrast": 18, "saturation": 6, "vignette": 25},
                    "balance": {"rs": -0.08, "bs": 0.1, "rh": 0.08, "bh": -0.08}},
    "golden": {"label": "Golden Hour", "values": {"temperature": 38, "saturation": 14, "contrast": 8, "vignette": 20},
               "balance": {"rh": 0.05, "gh": 0.02, "bh": -0.06}},
    "clean": {"label": "Clean & Bright", "values": {"brightness": 7, "contrast": 6, "saturation": 10, "temperature": 4}},
    "portrait": {"label": "Skin Glow", "values": {"brightness": 4, "contrast": 4, "saturation": 4, "temperature": 12, "vignette": 15},
                 "balance": {"rm": 0.02, "gm": -0.01, "rh": 0.03}},
    "film": {"label": "Film", "values": {"contrast": 12, "saturation": -10, "vignette": 25, "grain": 35}, "fade": 0.06,
             "balance": {"rm": 0.02, "bs": 0.03, "bh": -0.02}},
    "cinematic": {"label": "Cinematic", "values": {"contrast": 20, "saturation": -14, "brightness": -4, "vignette": 35},
                  "balance": {"rs": -0.07, "gs": -0.01, "bs": 0.09, "rh": 0.07, "gh": 0.01, "bh": -0.07}},
    "matte": {"label": "Matte", "values": {"contrast": -6, "saturation": -12}, "fade": 0.1},
    "moody": {"label": "Moody", "values": {"brightness": -8, "contrast": 22, "saturation": -30, "temperature": -10, "vignette": 45},
              "balance": {"bs": 0.05}},
    "night": {"label": "Night City", "values": {"contrast": 16, "saturation": 10, "temperature": -20, "vignette": 30},
              "balance": {"bs": 0.08, "rh": 0.05}},
    "vivid": {"label": "Vivid Pop", "values": {"contrast": 14, "saturation": 32}},
    "warm": {"label": "Warm", "values": {"temperature": 38, "saturation": 8, "contrast": 6}},
    "cool": {"label": "Cool", "values": {"temperature": -36, "contrast": 6, "saturation": -4}},
    "vintage": {"label": "Vintage", "values": {"saturation": -28, "temperature": 22, "contrast": -8, "vignette": 30, "grain": 25},
                "fade": 0.08, "balance": {"rh": 0.04, "bh": -0.08}},
    "noir": {"label": "Noir", "values": {"saturation": -100, "contrast": 35, "vignette": 40, "grain": 20}},
    "bw": {"label": "Black & white", "values": {"saturation": -100, "contrast": 22}},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ffmpeg_bin() -> str:
    return os.getenv("CLYP_FFMPEG_PATH") or os.getenv("FFMPEG_PATH") or "ffmpeg"


def ffprobe_bin() -> str:
    return os.getenv("CLYP_FFPROBE_PATH") or os.getenv("FFPROBE_PATH") or "ffprobe"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def num(value: float) -> str:
    return (f"{value:.4f}".rstrip("0").rstrip(".")) or "0"


def clamp(value: Any, low: float, high: float, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(number) or math.isinf(number):
        return fallback
    return max(low, min(high, number))


def tail(text: str, lines: int = 12) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


def fail(message: str, status: int = 400):
    return jsonify({"ok": False, "message": message}), status


def run(args: list[str], timeout: int = 600, cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, cwd=cwd)
    except FileNotFoundError:
        raise RuntimeError(f"{Path(args[0]).name} was not found. Install FFmpeg or set CLYP_FFMPEG_PATH / CLYP_FFPROBE_PATH in .env.")
    if result.returncode != 0:
        raise RuntimeError("Media processing failed.\n" + tail(result.stderr.decode("utf-8", "replace")))
    return result


def project_dir(pid: str) -> Path:
    if not PROJECT_ID.match(pid or ""):
        raise KeyError(pid)
    return VIDEO_ROOT / pid


def load_project(pid: str) -> dict[str, Any]:
    path = project_dir(pid) / "project.json"
    if not path.is_file():
        raise KeyError(pid)
    project = json.loads(path.read_text(encoding="utf-8"))
    # Projects saved by an older build may lack newer settings; fill them from the defaults.
    # Their chosen look predates the strength control, so keep it at full strength.
    if isinstance(project.get("grade"), dict) and "strength" not in project["grade"]:
        project["grade"]["strength"] = 100
    for section, defaults in default_settings().items():
        project[section] = {**defaults, **(project.get(section) or {})}
    return project


def save_project(project: dict[str, Any]) -> None:
    path = project_dir(project["id"]) / "project.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def update_render(pid: str, **fields: Any) -> None:
    with _lock:
        project = load_project(pid)
        project["render"] = {**project.get("render", {}), **fields}
        save_project(project)


def probe(path: Path) -> dict[str, Any]:
    result = run([ffprobe_bin(), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=60)
    data = json.loads(result.stdout or b"{}")
    streams = data.get("streams") or []
    stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not stream:
        raise RuntimeError("No video track was found in this file.")
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    # Phone videos often carry rotation metadata; FFmpeg auto-rotates on decode, so swap to match.
    rotation = 0
    try:
        rotation = int(float((stream.get("tags") or {}).get("rotate") or 0))
    except ValueError:
        pass
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            rotation = int(float(side["rotation"]))
    if abs(rotation) % 180 == 90:
        width, height = height, width
    duration = float((data.get("format") or {}).get("duration") or stream.get("duration") or 0)
    return {
        "width": width,
        "height": height,
        "duration": round(duration, 3),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
    }


def even(value: int) -> int:
    return max(2, value - value % 2)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def default_settings() -> dict[str, Any]:
    return {
        "caption_style": {"enabled": True, "preset": "signature", "position": "bottom", "size": 100, "highlight": True, "highlight_color": CAPTION_STYLES["signature"]["highlight"], "words": 5,
                          "effect": "shadow", "glow_color": "#FFFFFF", "glow_strength": 60},
        "sound": {"id": "", "volume": 0.25, "original_volume": 1.0, "start": 0.0, "duck": True},
        "grade": {"auto": True, "preset": "pro", "strength": 70, **{key: 0 for key in GRADE_KEYS}},
    }


def safe_hex(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", text) else fallback


def clean_captions(items: Any, duration: float) -> list[dict[str, Any]]:
    out = []
    limit = duration if duration > 0 else 86400
    for item in (items if isinstance(items, list) else [])[:3000]:
        if not isinstance(item, dict):
            continue
        text = re.sub(r"[ \t]+", " ", str(item.get("text") or "")).strip()[:400]
        start = clamp(item.get("start"), 0, limit, 0)
        end = clamp(item.get("end"), 0, limit, start + 1)
        if end <= start:
            end = min(limit, start + 0.5)
        out.append({"start": round(start, 3), "end": round(end, 3), "text": text})
    out.sort(key=lambda c: c["start"])
    return out


def apply_settings(project: dict[str, Any], data: dict[str, Any]) -> None:
    if "name" in data:
        project["name"] = str(data.get("name") or "").strip()[:120] or project["name"]
    if "captions" in data:
        project["captions"] = clean_captions(data.get("captions"), project["duration"])

    style = data.get("caption_style")
    if isinstance(style, dict):
        current = project["caption_style"]
        preset = str(style.get("preset", current["preset"]))
        if preset in CAPTION_STYLES and preset != current["preset"]:
            current["preset"] = preset
            current["highlight_color"] = CAPTION_STYLES[preset]["highlight"]
        position = str(style.get("position", current["position"]))
        current["position"] = position if position in {"bottom", "middle", "top"} else current["position"]
        current["size"] = int(clamp(style.get("size", current["size"]), 50, 160, 100))
        current["words"] = int(clamp(style.get("words", current["words"]), 1, 10, 5))
        current["enabled"] = bool(style.get("enabled", current["enabled"]))
        current["highlight"] = bool(style.get("highlight", current["highlight"]))
        current["highlight_color"] = safe_hex(style.get("highlight_color"), current["highlight_color"])
        effect = str(style.get("effect", current["effect"]))
        current["effect"] = effect if effect in {"shadow", "glow", "none"} else current["effect"]
        current["glow_color"] = safe_hex(style.get("glow_color"), current["glow_color"])
        current["glow_strength"] = int(clamp(style.get("glow_strength", current["glow_strength"]), 0, 100, 60))

    sound = data.get("sound")
    if isinstance(sound, dict):
        current = project["sound"]
        sound_id = str(sound.get("id", current["id"]) or "")
        current["id"] = sound_id if (not sound_id or resolve_sound(sound_id)) else current["id"]
        current["volume"] = round(clamp(sound.get("volume", current["volume"]), 0, 1, 0.25), 3)
        current["original_volume"] = round(clamp(sound.get("original_volume", current["original_volume"]), 0, 1.5, 1), 3)
        current["start"] = round(clamp(sound.get("start", current["start"]), 0, 3600, 0), 2)
        current["duck"] = bool(sound.get("duck", current["duck"]))

    grade = data.get("grade")
    if isinstance(grade, dict):
        current = project["grade"]
        preset = str(grade.get("preset", current["preset"]))
        current["preset"] = preset if preset in GRADE_PRESETS else current["preset"]
        current["auto"] = bool(grade.get("auto", current["auto"]))
        current["strength"] = int(clamp(grade.get("strength", current["strength"]), 0, 150, 70))
        for key in GRADE_KEYS:
            low = 0 if key in ("vignette", "grain") else -100
            current[key] = int(clamp(grade.get(key, current[key]), low, 100, 0))


def public_project(project: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in project.items() if k != "segments"}
    out["has_transcript"] = bool(project.get("segments"))
    return out


# ---------------------------------------------------------------------------
# Captions
# ---------------------------------------------------------------------------

def caption_chunks(segments: list[dict[str, Any]], words_per: int) -> list[dict[str, Any]]:
    """Split transcript segments into short on-screen captions, timed by word length."""
    out = []
    for seg in segments:
        words = str(seg.get("text") or "").split()
        if not words:
            continue
        start, end = float(seg["start"]), float(seg["end"])
        span = max(0.3, end - start)
        total = sum(len(w) + 1 for w in words)
        groups = [words[i:i + words_per] for i in range(0, len(words), words_per)]
        cursor = start
        for index, group in enumerate(groups):
            finish = end if index == len(groups) - 1 else cursor + span * sum(len(w) + 1 for w in group) / total
            out.append({"start": round(cursor, 3), "end": round(max(cursor + 0.25, finish), 3), "text": " ".join(group)})
            cursor = finish
    return out


def ass_colour(hex_value: str, alpha: float = 0.0) -> str:
    """#RRGGBB + transparency (0 opaque .. 1 clear) to ASS &HAABBGGRR."""
    r, g, b = hex_value[1:3], hex_value[3:5], hex_value[5:7]
    return f"&H{round(max(0, min(1, alpha)) * 255):02X}{b}{g}{r}".upper()


def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{secs:05.2f}"


def ass_text(text: str) -> str:
    # libass has no reliable escape for braces/backslashes, so swap them for look-alikes.
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", " ").strip()


STOPWORDS = set("""a an and are as at be been but by can could did do does for from had has have he her him his how i if in into is it its
just me my no not of on or our out she so than that the their them then there these they this to too up us was we were what when where which
who will with would you your about after again all also am any because before being both each few more most much only other over own same
some such very like really gonna wanna yeah okay oh""".split())


def emphasis_words(text: str, auto: bool = True) -> list[tuple[str, bool]]:
    """Split caption text into (word, emphasised). *word* or *several words* mark emphasis;
    with auto=True a caption without any marks gets its strongest word emphasised."""
    out: list[tuple[str, bool]] = []
    active = False
    for raw in text.split():
        word = raw.replace("*", "")
        if not word:
            continue
        opens = raw.startswith("*")
        closes = "*" in (raw[1:] if opens else raw)
        out.append((word, active or opens))
        if opens and not closes:
            active = True
        elif closes:
            active = False
    if auto and out and not any(e for _, e in out):
        def letters(w: str) -> str:
            return re.sub(r"[^\w']", "", w).lower()
        candidates = [i for i, (w, _) in enumerate(out) if len(letters(w)) >= 4 and letters(w) not in STOPWORDS]
        if candidates:
            best = max(candidates, key=lambda i: len(letters(out[i][0])))
            out[best] = (out[best][0], True)
    return out


def word_shares(words: list[str], total: int) -> list[int]:
    """Split `total` centiseconds across words by length; Gemini only gives phrase timings."""
    weights = [len(w) + 1 for w in words]
    shares, spent = [], 0
    for index, weight in enumerate(weights):
        share = total - spent if index == len(words) - 1 else round(total * weight / sum(weights))
        spent += share
        shares.append(max(1, share))
    return shares


def build_ass(project: dict[str, Any], captions: list[dict[str, Any]]) -> str:
    width, height = even(project["width"]), even(project["height"])
    settings = project["caption_style"]
    style = CAPTION_STYLES.get(settings["preset"], CAPTION_STYLES["signature"])
    scale = min(width, height) / 1080 * settings["size"] / 100
    highlight = settings["highlight"]
    build = style["kind"] == "build"
    if build:
        # A left-aligned block in the lower third that grows word by word.
        alignment = {"bottom": 1, "middle": 4, "top": 7}[settings["position"]]
        margin_v = round(height * (0.15 if settings["position"] == "bottom" else 0.1))
        margin_h = round(width * 0.09)
        primary = secondary = ass_colour(style["base"])
    else:
        alignment = {"bottom": 2, "middle": 5, "top": 8}[settings["position"]]
        margin_v = round(height * 0.085)
        margin_h = round(width * 0.065)
        # With \kf karaoke, words start in SecondaryColour and fill to PrimaryColour as they are spoken.
        primary = ass_colour(settings["highlight_color"] if highlight else style["base"])
        secondary = ass_colour(style["base"])
    outline = ass_colour(style["outline"])
    back = ass_colour(style["back"], 1 - style["back_alpha"])
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 0",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Caption,{style['font']},{round(style['size'] * scale)},{primary},{secondary},{outline},{back},{0 if build else -1},0,0,0,100,100,"
        f"{num(style.get('spacing', 0) * scale)},0,{3 if style['box'] else 1},{num(style['outline_size'] * scale)},{num(style['shadow'] * scale)},"
        f"{alignment},{margin_h},{margin_h},{margin_v},1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for caption in captions:
        text = ass_text(caption["text"])
        if not text.replace("*", "").strip():
            continue
        if style["upper"]:
            text = text.upper()
        start, end = caption["start"], caption["end"]
        total_cs = round((end - start) * 100)
        if build:
            words = emphasis_words(text, auto=highlight)
            shares = word_shares([w for w, _ in words], max(len(words), total_cs))
            size = round(style["emphasis_scale"] * 100)
            emph = f"\\fn{style['emphasis_font']}\\fscx{size}\\fscy{size}"
            emph_colour = ass_colour(settings["highlight_color"])[2:] + "&"
            # Effect layers sit under the text. Each is (tags, alpha override, opacity); every
            # word fades its layer in at the moment it is spoken.
            effect = settings["effect"]
            layers: list[tuple[str, str, float]] = []
            if effect == "shadow":
                # A blurred black copy of the text acts as a soft drop shadow.
                layers.append((f"\\1c&H000000&\\bord0\\shad0\\blur{num(max(2.0, 7 * scale))}", "\\alpha", 0.6))
            elif effect == "glow":
                # Two blurred borders in the glow colour (wide halo + tight core); the fill stays clear.
                g = settings["glow_strength"] / 100
                colour = ass_colour(settings["glow_color"])[2:] + "&"
                for bord, blur, opacity in ((3 + 6 * g, 10 + 18 * g, 0.35 + 0.45 * g), (1 + 2 * g, 3 + 5 * g, 0.6 + 0.4 * g)):
                    layers.append((f"\\1a&HFF&\\3c&H{colour}\\bord{num(bord * scale)}\\blur{num(blur * scale)}\\shad0", "\\3a", opacity))
            layers.append(("", "\\alpha", 1.0))
            for layer, (effect_tags, alpha_tag, opacity) in enumerate(layers):
                is_text = layer == len(layers) - 1
                visible = f"&H{round((1 - opacity) * 255):02X}&"
                parts, at_ms = [], 0
                for (word, emphasised), share in zip(words, shares):
                    tags = "\\r"
                    if emphasised and highlight:
                        tags += emph + (f"\\1c&H{emph_colour}" if is_text else "")
                    tags += effect_tags + f"{alpha_tag}&HFF&\\t({at_ms},{at_ms + 70},{alpha_tag}{visible})"
                    parts.append(f"{{{tags}}}{word}")
                    at_ms += share * 10
                lines.append(f"Dialogue: {layer},{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{' '.join(parts)}")
        else:
            words = [w for w, _ in emphasis_words(text, auto=False)]
            body = " ".join(words)
            if highlight:
                shares = word_shares(words, max(len(words), total_cs))
                body = " ".join(f"{{\\kf{share}}}{word}" for word, share in zip(words, shares))
            intro = "{\\fad(70,110)\\fscx92\\fscy92\\t(0,130,\\fscx100\\fscy100)}"
            lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{intro}{body}")
    return "\n".join(lines) + "\n"


def transcribe_project(pid: str) -> dict[str, Any]:
    project = load_project(pid)
    if not project["has_audio"]:
        raise RuntimeError("This video has no audio track to transcribe. Add captions by hand instead.")
    pdir = project_dir(pid)
    source = pdir / project["source"]
    tmp = pdir / "tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    chunk = int(clamp(os.getenv("CLYP_TRANSCRIBE_CHUNK_SECONDS") or os.getenv("TRANSCRIPTION_CHUNK_SECONDS") or 240, 60, 600, 240))
    duration = max(0.1, project["duration"])
    segments: list[dict[str, Any]] = []
    previous = ""
    try:
        for index in range(max(1, math.ceil(duration / chunk))):
            offset = index * chunk
            length = min(chunk, duration - offset)
            if length <= 0.05:
                break
            audio = tmp / f"audio_{index:03d}.mp3"
            run([ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-ss", num(offset), "-i", str(source), "-t", num(length),
                 "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", str(audio)])
            data = ai_post("transcribe", {
                "audio_b64": base64.b64encode(audio.read_bytes()).decode("ascii"),
                "mime": "audio/mp3",
                "duration": length,
                "previous": previous,
            })
            for seg in data.get("segments") or []:
                segments.append({"start": round(seg["start"] + offset, 3), "end": round(min(duration, seg["end"] + offset), 3), "text": seg["text"]})
            previous = " ".join(s["text"] for s in segments[-3:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if not segments:
        raise RuntimeError("Gemini didn't hear any speech in this video.")
    with _lock:
        project = load_project(pid)
        project["segments"] = segments
        project["captions"] = caption_chunks(segments, project["caption_style"]["words"])
        project["updated_at"] = now_iso()
        save_project(project)
    return project


def ai_post(route: str, payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    endpoint = os.getenv("CLYP_AI_ENDPOINT", "http://127.0.0.1:8100").rstrip("/")
    req = urllib.request.Request(
        f"{endpoint}/{route}",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json", "X-Internal-Token": os.getenv("CLYP_AI_INTERNAL_TOKEN", "change-me")},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8"))
        except Exception:
            data = {"ok": False, "message": str(exc)}
    except Exception as exc:
        raise RuntimeError(f"Python AI service unavailable: {exc}")
    if not data.get("ok"):
        raise RuntimeError(data.get("message") or "Transcription failed")
    return data


# ---------------------------------------------------------------------------
# Colour grading
# ---------------------------------------------------------------------------

def analyse_video(project: dict[str, Any]) -> dict[str, Any]:
    """Sample frames with FFmpeg signalstats and work out an automatic correction.

    Returns slider-scale corrections for exposure, contrast, saturation and white balance,
    plus a plain-language summary for the editor.
    """
    pdir = project_dir(project["id"])
    duration = max(0.1, project["duration"])
    samples = 10 if duration > 3 else 4
    keys = ("YAVG", "YLOW", "YHIGH", "SATAVG", "UAVG", "VAVG")
    stats: dict[str, list[float]] = {k: [] for k in keys}
    for index in range(samples):
        at = duration * (index + 0.5) / samples
        try:
            result = run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-ss", num(at), "-i", project["source"], "-frames:v", "1",
                          "-vf", "scale=160:-2,signalstats,metadata=print:file=-", "-f", "null", "-"], timeout=60, cwd=pdir)
        except Exception:
            continue
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            key, _, value = line.strip().rpartition("=")
            name = key.rsplit(".", 1)[-1]
            if name in stats:
                try:
                    stats[name].append(float(value))
                except ValueError:
                    pass
    if not stats["YAVG"]:
        return {"values": {}, "summary": ["Couldn't analyse this video, so no automatic correction is applied."], "stats": {}}

    def median(values: list[float]) -> float:
        ordered = sorted(values)
        return ordered[len(ordered) // 2]

    m = {k: median(v) for k, v in stats.items() if v}
    values: dict[str, int] = {}
    summary: list[str] = []
    # Exposure: aim the average luma at a comfortable mid-grey (8-bit limited range).
    exposure = clamp((118 - m["YAVG"]) / 255 / 0.2 * 100 * 0.7, -35, 35, 0)
    if abs(exposure) >= 3:
        values["brightness"] = round(exposure)
        summary.append("Brightened the footage" if exposure > 0 else "Brought down bright footage")
    # Contrast: stretch a flat image towards a healthy tonal range, leave punchy footage alone.
    spread = max(20.0, m.get("YHIGH", 200) - m.get("YLOW", 40))
    contrast = clamp((150 / spread - 1) / 0.6 * 100 * 0.6, -15, 35, 0)
    if abs(contrast) >= 3:
        values["contrast"] = round(contrast)
        summary.append("Added depth to flat footage" if contrast > 0 else "Softened harsh contrast")
    # Saturation: lift dull colour, calm oversaturated colour; skip black-and-white footage.
    sat = m.get("SATAVG", 40)
    if sat > 6:
        saturation = clamp((42 / sat - 1) * 100 * 0.5, -25, 30, 0)
        if abs(saturation) >= 3:
            values["saturation"] = round(saturation)
            summary.append("Richer colour" if saturation > 0 else "Calmed oversaturated colour")
    # White balance: U>128 is a blue cast, V>128 red; both low is a green cast. Correct ~60%
    # so warm, intentional scenes are not flattened to grey.
    du, dv = m.get("UAVG", 128) - 128, m.get("VAVG", 128) - 128
    temperature = clamp(-(dv - du) * 3, -35, 35, 0)
    tint = clamp(-(du + dv) * 3, -30, 30, 0)
    if abs(temperature) >= 4:
        values["temperature"] = round(temperature)
        summary.append("Warmed a cold colour cast" if temperature > 0 else "Cooled an orange colour cast")
    if abs(tint) >= 4:
        values["tint"] = round(tint)
        summary.append("Removed a green tint" if tint > 0 else "Removed a magenta tint")
    if not summary:
        summary.append("Exposure and colour already look balanced")
    return {"values": values, "summary": summary, "stats": {k: round(v, 1) for k, v in m.items()}}


def ensure_analysis(pid: str) -> dict[str, Any]:
    project = load_project(pid)
    if project.get("analysis"):
        return project
    analysis = analyse_video(project)
    with _lock:
        project = load_project(pid)
        project["analysis"] = analysis
        save_project(project)
    return project


def grade_values(grade: dict[str, Any], analysis: dict[str, Any] | None = None) -> dict[str, int]:
    """Final slider-scale values: automatic correction + look x strength + the user's sliders."""
    look = GRADE_PRESETS.get(grade.get("preset"), GRADE_PRESETS["none"])["values"]
    strength = int(grade.get("strength", 100)) / 100
    auto = (analysis or {}).get("values", {}) if grade.get("auto") else {}
    out = {}
    for key in GRADE_KEYS:
        low = 0 if key in ("vignette", "grain") else -100
        out[key] = int(clamp(auto.get(key, 0) + look.get(key, 0) * strength + int(grade.get(key) or 0), low, 100, 0))
    return out


def grade_filters(grade: dict[str, Any], analysis: dict[str, Any] | None = None) -> list[str]:
    v = grade_values(grade, analysis)
    look = GRADE_PRESETS.get(grade.get("preset"), GRADE_PRESETS["none"])
    strength = int(grade.get("strength", 100)) / 100
    filters = []
    balance = {k: val * strength for k, val in (look.get("balance") or {}).items()}
    t, n = v["temperature"] / 100, v["tint"] / 100
    for key, extra in (("rm", 0.18 * t), ("bm", -0.18 * t), ("rh", 0.1 * t), ("bh", -0.1 * t), ("gm", -0.12 * n)):
        balance[key] = balance.get(key, 0) + extra
    balance = {k: clamp(val, -1, 1, 0) for k, val in balance.items() if abs(val) >= 0.001}
    if balance:
        filters.append("colorbalance=" + ":".join(f"{k}={num(val)}" for k, val in sorted(balance.items())))
    if v["brightness"] or v["contrast"] or v["saturation"]:
        filters.append(
            f"eq=brightness={num(v['brightness'] / 100 * 0.2)}"
            f":contrast={num(1 + v['contrast'] / 100 * 0.6)}"
            f":saturation={num(max(0.0, 1 + v['saturation'] / 100))}"
        )
    fade = float(look.get("fade") or 0) * strength
    if fade >= 0.005:
        filters.append(f"colorlevels=romin={num(fade)}:gomin={num(fade)}:bomin={num(fade)}")
    if v["vignette"]:
        filters.append(f"vignette=angle={num(0.15 + 0.65 * v['vignette'] / 100)}")
    if v["grain"]:
        filters.append(f"noise=alls={round(v['grain'] * 0.22)}:allf=t")
    return filters


# ---------------------------------------------------------------------------
# Sounds
# ---------------------------------------------------------------------------

def resolve_sound(sound_id: str) -> Path | None:
    kind, _, name = (sound_id or "").partition(":")
    folder = {"library": SOUND_ROOT, "upload": SOUND_UPLOADS}.get(kind)
    if not folder or not name or secure_filename(name) != name or Path(name).suffix.lower() not in SOUND_EXTS:
        return None
    path = folder / name
    return path if path.is_file() else None


def sound_duration(path: Path) -> float:
    key, mtime = str(path), path.stat().st_mtime
    cached = _sound_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        result = run([ffprobe_bin(), "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], timeout=20)
        duration = round(float(result.stdout.decode().strip() or 0), 2)
    except Exception:
        duration = 0.0
    _sound_cache[key] = (mtime, duration)
    return duration


def list_sounds() -> list[dict[str, Any]]:
    out = []
    for kind, folder in (("library", SOUND_ROOT), ("upload", SOUND_UPLOADS)):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir()):
            if path.is_file() and path.suffix.lower() in SOUND_EXTS:
                out.append({
                    "id": f"{kind}:{path.name}",
                    "kind": kind,
                    "title": re.sub(r"[-_]+", " ", path.stem).strip().title(),
                    "duration": sound_duration(path),
                })
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def video_chain(project: dict[str, Any], ass_name: str | None) -> list[str]:
    chain = grade_filters(project["grade"], project.get("analysis"))
    chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
    if ass_name:
        chain.append(f"ass={ass_name}")
    return chain


def write_captions(project: dict[str, Any], pdir: Path, name: str) -> str | None:
    captions = [c for c in project.get("captions") or [] if c["text"].strip()]
    if not project["caption_style"]["enabled"] or not captions:
        return None
    (pdir / name).write_text(build_ass(project, captions), encoding="utf-8")
    return name


def build_render_args(project: dict[str, Any], pdir: Path, output: Path) -> list[str]:
    duration = max(0.1, project["duration"])
    # Run with cwd=pdir so the ass filter can take a bare filename; Windows drive
    # letters otherwise need fragile filtergraph escaping.
    args = [ffmpeg_bin(), "-y", "-hide_banner", "-nostats", "-progress", "pipe:1", "-i", project["source"]]
    sound = project["sound"]
    music = resolve_sound(sound["id"])
    if music:
        args += ["-stream_loop", "-1", "-i", str(music)]

    ass_name = write_captions(project, pdir, "captions.ass")
    filters = ["[0:v]" + ",".join(video_chain(project, ass_name) + ["format=yuv420p"]) + "[vout]"]

    audio_out = None
    voice = None
    if project["has_audio"]:
        filters.append(f"[0:a]aresample=48000,volume={num(sound['original_volume'])}[voice0]")
        voice = "voice0"
    if music:
        fade_at = max(0.0, duration - 1.5)
        filters.append(
            f"[1:a]atrim=start={num(sound['start'])}:duration={num(duration)},asetpts=PTS-STARTPTS,aresample=48000,"
            f"volume={num(sound['volume'])},afade=t=in:d=0.4,afade=t=out:st={num(fade_at)}:d=1.5[music]"
        )
        if voice and sound["duck"] and sound["original_volume"] > 0:
            filters.append("[voice0]asplit=2[voice][side]")
            filters.append("[music][side]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[ducked]")
            filters.append("[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[aout]")
        elif voice:
            filters.append("[voice0][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[aout]")
        else:
            filters.append("[music]alimiter=limit=0.95[aout]")
        audio_out = "aout"
    elif voice:
        audio_out = voice

    args += ["-filter_complex", ";".join(filters), "-map", "[vout]"]
    if audio_out:
        args += ["-map", f"[{audio_out}]", "-c:a", "aac", "-b:a", "192k"]
    args += ["-t", num(duration), "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-movflags", "+faststart", str(output)]
    return args


def render_worker(pid: str) -> None:
    try:
        project = ensure_analysis(pid)
        pdir = project_dir(pid)
        exports = pdir / "exports"
        exports.mkdir(exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", project["name"].lower()).strip("-")[:40] or "video"
        output = exports / f"clyp-{slug}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.mp4"
        args = build_render_args(project, pdir, output)
        duration = max(0.1, project["duration"])
        log_path = pdir / "render.log"
        with open(log_path, "w", encoding="utf-8", errors="replace") as log:
            try:
                proc = subprocess.Popen(args, cwd=pdir, stdout=subprocess.PIPE, stderr=log, text=True)
            except FileNotFoundError:
                raise RuntimeError("FFmpeg was not found. Install it or set CLYP_FFMPEG_PATH in .env.")
            last = 0.0
            for line in proc.stdout or []:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and value.isdigit():
                    progress = min(0.99, int(value) / 1_000_000 / duration)
                    if time.monotonic() - last > 0.5:
                        update_render(pid, progress=round(progress, 3))
                        last = time.monotonic()
            code = proc.wait()
        if code != 0 or not output.is_file():
            output.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg could not export this video.\n" + tail(log_path.read_text(encoding="utf-8", errors="replace")))
        update_render(pid, status="done", progress=1, output=output.name, error="", finished_at=now_iso())
    except Exception as exc:
        try:
            update_render(pid, status="error", error=str(exc), finished_at=now_iso())
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@video.get("/api/video/options")
def options():
    return jsonify({
        "ok": True,
        "caption_styles": CAPTION_STYLES,
        # jsonify sorts object keys, so send display order separately.
        "caption_order": list(CAPTION_STYLES),
        "grade_presets": GRADE_PRESETS,
        "grade_order": list(GRADE_PRESETS),
        "grade_keys": GRADE_KEYS,
        "defaults": default_settings(),
    })


@video.get("/api/video/projects")
def projects_list():
    items = []
    if VIDEO_ROOT.is_dir():
        for folder in VIDEO_ROOT.iterdir():
            try:
                project = load_project(folder.name)
            except (KeyError, ValueError, OSError):
                continue
            items.append({k: project[k] for k in ("id", "name", "duration", "width", "height", "created_at", "updated_at")})
    items.sort(key=lambda p: p["updated_at"], reverse=True)
    return jsonify({"ok": True, "projects": items})


@video.post("/api/video/projects")
def projects_create():
    upload = request.files.get("video")
    if not upload or not upload.filename:
        return fail("Choose a video file to upload.", 422)
    ext = Path(upload.filename).suffix.lower()
    if ext not in VIDEO_EXTS:
        return fail("Clyp accepts MP4, MOV, M4V, WEBM, MKV or AVI videos.", 415)
    pid = uuid.uuid4().hex[:12]
    pdir = project_dir(pid)
    pdir.mkdir(parents=True)
    source = f"source{ext}"
    try:
        upload.save(pdir / source)
        meta = probe(pdir / source)
        if meta["duration"] <= 0 or not meta["width"]:
            raise RuntimeError("Clyp couldn't read the length or size of this video.")
        stamp = now_iso()
        project = {
            "id": pid,
            "name": (Path(upload.filename).stem.strip() or "Untitled video")[:120],
            "source": source,
            **meta,
            "created_at": stamp,
            "updated_at": stamp,
            "captions": [],
            "segments": [],
            **default_settings(),
            "render": {"status": "idle", "progress": 0, "output": "", "error": "", "finished_at": ""},
        }
        save_project(project)
        try:
            run([ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-ss", num(min(1.0, meta["duration"] / 2)), "-i", source,
                 "-frames:v", "1", "-vf", "scale=360:-2", str(pdir / "thumb.jpg")], timeout=60, cwd=pdir)
        except Exception:
            pass  # a missing thumbnail only affects the library card
        project = ensure_analysis(pid)
    except Exception as exc:
        shutil.rmtree(pdir, ignore_errors=True)
        return fail(str(exc), 422)
    return jsonify({"ok": True, "project": public_project(project)})


@video.get("/api/video/projects/<pid>")
def projects_get(pid: str):
    try:
        return jsonify({"ok": True, "project": public_project(ensure_analysis(pid))})
    except KeyError:
        return fail("Video project not found.", 404)


@video.put("/api/video/projects/<pid>")
def projects_update(pid: str):
    data = request.get_json(silent=True) or {}
    try:
        with _lock:
            project = load_project(pid)
            apply_settings(project, data)
            project["updated_at"] = now_iso()
            save_project(project)
    except KeyError:
        return fail("Video project not found.", 404)
    return jsonify({"ok": True, "project": public_project(project)})


@video.delete("/api/video/projects/<pid>")
def projects_delete(pid: str):
    try:
        project = load_project(pid)
    except KeyError:
        return fail("Video project not found.", 404)
    if project.get("render", {}).get("status") == "running":
        return fail("Wait for the export to finish before deleting this video.", 409)
    shutil.rmtree(project_dir(pid), ignore_errors=True)
    return jsonify({"ok": True})


@video.get("/api/video/projects/<pid>/source")
def projects_source(pid: str):
    try:
        project = load_project(pid)
    except KeyError:
        return fail("Video project not found.", 404)
    return send_file(project_dir(pid) / project["source"], conditional=True)


@video.get("/api/video/projects/<pid>/thumb")
def projects_thumb(pid: str):
    try:
        path = project_dir(pid) / "thumb.jpg"
    except KeyError:
        return fail("Video project not found.", 404)
    if not path.is_file():
        return fail("No thumbnail.", 404)
    return send_file(path, max_age=3600)


@video.post("/api/video/projects/<pid>/transcribe")
def projects_transcribe(pid: str):
    try:
        project = transcribe_project(pid)
    except KeyError:
        return fail("Video project not found.", 404)
    except Exception as exc:
        return fail(str(exc), 502)
    return jsonify({"ok": True, "project": public_project(project)})


@video.post("/api/video/projects/<pid>/resplit")
def projects_resplit(pid: str):
    """Re-chunk the saved transcript after the user changes words-per-caption."""
    try:
        with _lock:
            project = load_project(pid)
            if not project.get("segments"):
                return fail("Generate captions with AI first.", 409)
            project["captions"] = caption_chunks(project["segments"], project["caption_style"]["words"])
            project["updated_at"] = now_iso()
            save_project(project)
    except KeyError:
        return fail("Video project not found.", 404)
    return jsonify({"ok": True, "project": public_project(project)})


@video.get("/api/video/projects/<pid>/frame")
def projects_frame(pid: str):
    """One frame rendered by FFmpeg exactly as the export will look (grade + captions)."""
    try:
        project = load_project(pid)
    except KeyError:
        return fail("Video project not found.", 404)
    pdir = project_dir(pid)
    at = clamp(request.args.get("t"), 0, max(0.0, project["duration"] - 0.05), 0)
    ass_name = write_captions(project, pdir, "preview.ass")
    chain = video_chain(project, ass_name) + ["scale=-2:'min(720,ih)'"]
    try:
        # -copyts keeps the seeked timestamp so the caption track lines up with the frame.
        result = run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-ss", num(at), "-copyts", "-i", project["source"],
                      "-frames:v", "1", "-vf", ",".join(chain), "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "3", "-"], timeout=60, cwd=pdir)
    except Exception as exc:
        return fail(str(exc), 500)
    return Response(result.stdout, content_type="image/jpeg", headers={"Cache-Control": "no-store"})


@video.post("/api/video/projects/<pid>/render")
def projects_render(pid: str):
    try:
        with _lock:
            project = load_project(pid)
            if project.get("render", {}).get("status") == "running":
                return fail("An export is already running for this video.", 409)
            project["render"] = {"status": "running", "progress": 0, "output": "", "error": "", "finished_at": "", "started_at": now_iso()}
            save_project(project)
    except KeyError:
        return fail("Video project not found.", 404)
    threading.Thread(target=render_worker, args=(pid,), daemon=True).start()
    return jsonify({"ok": True, "render": project["render"]})


@video.get("/api/video/projects/<pid>/render")
def projects_render_status(pid: str):
    try:
        return jsonify({"ok": True, "render": load_project(pid).get("render", {})})
    except KeyError:
        return fail("Video project not found.", 404)


@video.get("/api/video/projects/<pid>/export")
def projects_export(pid: str):
    try:
        project = load_project(pid)
    except KeyError:
        return fail("Video project not found.", 404)
    name = project.get("render", {}).get("output") or ""
    path = project_dir(pid) / "exports" / name
    if not name or not path.is_file():
        return fail("Export this video first.", 404)
    return send_file(path, conditional=True, as_attachment=request.args.get("download") == "1", download_name=name)


@video.get("/api/video/sounds")
def sounds_list():
    return jsonify({"ok": True, "sounds": list_sounds()})


@video.post("/api/video/sounds")
def sounds_upload():
    upload = request.files.get("sound")
    if not upload or not upload.filename:
        return fail("Choose an audio file to upload.", 422)
    name = secure_filename(upload.filename)
    if Path(name).suffix.lower() not in SOUND_EXTS:
        return fail("Clyp accepts WAV, MP3, M4A, AAC or OGG audio.", 415)
    SOUND_UPLOADS.mkdir(parents=True, exist_ok=True)
    target = SOUND_UPLOADS / name
    if target.exists():
        target = SOUND_UPLOADS / f"{target.stem}-{uuid.uuid4().hex[:6]}{target.suffix}"
    upload.save(target)
    return jsonify({"ok": True, "sound": {"id": f"upload:{target.name}", "kind": "upload", "title": re.sub(r"[-_]+", " ", target.stem).title(), "duration": sound_duration(target)}})


@video.get("/api/video/sounds/<sound_id>")
def sounds_file(sound_id: str):
    path = resolve_sound(sound_id)
    if not path:
        return fail("Sound not found.", 404)
    return send_file(path, conditional=True)
