from __future__ import annotations

import base64
import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from design_intelligence import DESIGN_PLAYBOOK, FEW_SHOT_PATTERNS

from flask import Flask, jsonify, request

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

ROOT = Path(__file__).resolve().parent


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


load_env_file(ROOT / ".env")

app = Flask(__name__)
TOKEN = os.getenv("CLYP_AI_INTERNAL_TOKEN", "change-me")
# GEMINI_API_KEY is the name the older PHP build wrote to .env; accept it so one .env serves both.
API_KEY = (os.getenv("CLYP_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
MODEL = os.getenv("CLYP_GEMINI_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
IMAGE_MODEL = os.getenv("CLYP_GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image").strip() or "gemini-3.1-flash-image"
IMAGE_FALLBACK_MODEL = os.getenv("CLYP_GEMINI_IMAGE_FALLBACK_MODEL", "gemini-2.5-flash-image").strip() or "gemini-2.5-flash-image"
AI_ENDPOINT = os.getenv("CLYP_AI_ENDPOINT", "http://127.0.0.1:8100").strip() or "http://127.0.0.1:8100"


def authorised(req) -> bool:
    return req.headers.get("X-Internal-Token") == TOKEN


def get_client():
    if genai is None:
        raise RuntimeError("google-genai is not installed. Run: py -m pip install -r requirements.txt")
    if not API_KEY:
        raise RuntimeError("CLYP_GEMINI_API_KEY (or GEMINI_API_KEY) is missing from .env")
    return genai.Client(api_key=API_KEY)


DESIGN_OUTPUT_RULES = r"""
Return ONLY one JSON object. Do not use Markdown or code fences.
Use this Clyp editable design contract. Omit optional properties when not needed:
{
  "name": "short project name",
  "design": {
    "canvas": {"width": 432, "height": 540, "bg": "#RRGGBB"},
    "palette": {
      "strategy": "monochromatic|analogous|complementary|split-complementary|triadic",
      "dominant": "#RRGGBB", "support": "#RRGGBB", "accent": "#RRGGBB",
      "light": "#RRGGBB", "dark": "#RRGGBB"
    },
    "layers": [
      {
        "type": "text|shape|image",
        "name": "layer name",
        "x": 0, "y": 0, "w": 100, "h": 50, "opacity": 1, "rotation": 0,

        "text": "text content for text",
        "size": 28, "weight": 600, "color": "#RRGGBB",
        "spacing": 0, "line": 1.05, "font": "font name", "align": "left|center|right",
        "text_stroke_color": "#RRGGBB", "text_stroke_width": 0,
        "shadow_color": "#RRGGBB", "shadow_opacity": 0, "shadow_x": 0, "shadow_y": 8, "shadow_blur": 18,

        "kind": "rect|ellipse|pill|line|triangle",
        "fill": "solid|linear", "color2": "#RRGGBB", "gradient_angle": 135,
        "radius": "0 or CSS radius", "stroke_color": "#RRGGBB", "stroke_width": 0,

        "asset_prompt": "ONLY for image layers that Clyp should generate; describe the photo/illustration asset without flyer text",
        "fit": "cover|contain", "blend_mode": "normal|multiply|screen|overlay|soft-light",
        "mask": "none|fade-bottom|fade-left|fade-right|soft-ellipse",
        "brightness": 1, "contrast": 1, "saturation": 1, "blur": 0
      }
    ]
  },
  "critique": {
    "direction": "one-sentence art direction",
    "hierarchy": "brief note", "colour": "brief note", "imagery": "brief note",
    "spacing": "brief note", "contrast": "brief note", "readability": "brief note"
  }
}
Use enough layers to make the design genuinely art-directed, usually 7-22. Do not add layers merely to reach a count.
If imagery is genuinely useful, include at most ONE generated hero image layer in the first direction. Give it a precise asset_prompt and compose text/shapes around it. Do not ask the image model to render the flyer typography, event details, logo or CTA.
Use image treatment fields intentionally; a photo should look integrated rather than pasted on.
Use shape layers for purposeful overlays, glow/light washes, gradients, highlight bars, rules, frames, badges, pills, wedges and panels.
For line shapes, h is thickness. For triangle shapes, x/y/w/h define its box.
"""


RECONSTRUCTION_OUTPUT_RULES = r"""
Return ONLY one JSON object. Do not use Markdown or code fences.
This is a tracing/reconstruction task, NOT a redesign task.
Use this compact Clyp reconstruction contract:
{
  "name": "short project name",
  "design": {
    "canvas": {"width": 405, "height": 540, "bg": "#RRGGBB"},
    "layers": [
      {
        "type": "text, shape, or image",
        "name": "descriptive layer name",
        "x": 0, "y": 0, "w": 100, "h": 50,
        "text": "exact visible text when type is text",
        "size": 28, "weight": 600,
        "color": "#RRGGBB",
        "spacing": 0, "line": 1.0,
        "font": "Impact, Arial Narrow, Arial Black, Arial, Georgia, Times New Roman, Trebuchet MS, Verdana, or system-ui",
        "align": "left, center, or right",
        "rotation": 0,
        "radius": "optional CSS radius",
        "opacity": 1,
        "kind": "rect|ellipse|pill|line|triangle for shape layers",
        "fill": "solid|linear for shape layers",
        "color2": "#RRGGBB", "gradient_angle": 135,
        "stroke_color": "#RRGGBB", "stroke_width": 0,
        "text_stroke_color": "#RRGGBB", "text_stroke_width": 0,
        "shadow_color": "#RRGGBB", "shadow_opacity": 0, "shadow_x": 0, "shadow_y": 8, "shadow_blur": 18,
        "brightness": 1, "contrast": 1, "saturation": 1, "blur": 0,
        "crop": [0, 0, 1000, 1000]
      }
    ]
  },
  "critique": {"fidelity": "brief note about what was traced vs approximated"}
}
For image layers, crop is [left, top, right, bottom] in NORMALISED SOURCE coordinates from 0 to 1000.
Image layers always refer to the uploaded source image; do not invent an external URL.
Use image layers for photographs, logos, icons, textured lighting, brush strokes, glows and other complex graphics that cannot be faithfully represented by simple editable primitives.
Use text layers for editable headline/body copy and transcribe it exactly.
Use shape layers only for genuinely simple solid rectangles, lines, circles, pills or blocks.
Return layers in visual back-to-front z-order.
Use as many layers as needed for fidelity, typically 10-30. Fidelity matters more than minimal layer count.
Do not include the same source text both inside a large image crop and again as an editable text layer unless unavoidable. Prefer image crops for photos/logos/icons; prefer editable layers for headline/body copy.
"""


def parse_json_response(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        left, right = raw.find("{"), raw.rfind("}")
        if left < 0 or right <= left:
            raise RuntimeError("Gemini returned an empty or non-JSON design response.")
        parsed = json.loads(raw[left:right + 1])
    if not isinstance(parsed, dict):
        raise RuntimeError("Gemini returned JSON, but not a Clyp design object.")
    return parsed


def safe_hex(value: Any, fallback: str) -> str:
    value = str(value or "").strip()
    return value if re.fullmatch(r"#[0-9A-Fa-f]{6}", value) else fallback


def clamp_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        value = int(round(float(value)))
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, value))


def clamp_float(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, value))


def safe_font(value: Any) -> str:
    raw = str(value or "system-ui").strip()[:80]
    allowed = {
        "bebas neue": "Bebas Neue",
        "oswald": "Oswald",
        "anton": "Anton",
        "archivo black": "Archivo Black",
        "barlow condensed": "Barlow Condensed",
        "league spartan": "League Spartan",
        "space grotesk": "Space Grotesk",
        "sora": "Sora",
        "montserrat": "Montserrat",
        "poppins": "Poppins",
        "plus jakarta sans": "Plus Jakarta Sans",
        "dm sans": "DM Sans",
        "work sans": "Work Sans",
        "source sans 3": "Source Sans 3",
        "dm serif display": "DM Serif Display",
        "cormorant garamond": "Cormorant Garamond",
        "libre baskerville": "Libre Baskerville",
        "manrope": "Manrope",
        "playfair display": "Playfair Display",
        "impact": "Impact",
        "arial narrow": "Arial Narrow",
        "arial black": "Arial Black",
        "arial": "Arial",
        "georgia": "Georgia",
        "times new roman": "Times New Roman",
        "trebuchet ms": "Trebuchet MS",
        "verdana": "Verdana",
        "system-ui": "system-ui",
        "inter": "Inter",
    }
    return allowed.get(raw.lower(), "system-ui")


def safe_choice(value: Any, allowed: set[str], fallback: str) -> str:
    raw = str(value or fallback).strip().lower()
    return raw if raw in allowed else fallback


def safe_radius(value: Any, fallback: str = "0") -> str:
    raw = str(value if value is not None else fallback).strip()[:30]
    if re.fullmatch(r"(?:\d+(?:\.\d+)?(?:px|%)?)(?:\s+\d+(?:\.\d+)?(?:px|%)?){0,3}", raw):
        return raw
    return fallback


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = safe_hex(value, "#000000")[1:]
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def relative_luminance(value: str) -> float:
    rgb = [c / 255.0 for c in hex_to_rgb(value)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in rgb]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(a: str, b: str) -> float:
    la, lb = relative_luminance(a), relative_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
WEEKDAY_RE = r"(mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?"
MONTH_RE = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"


def date_conflicts(design: dict[str, Any]) -> list[str]:
    """Find weekday + date pairs in text layers whose weekday is wrong, e.g. 'Friday 15 November 2026'."""
    import datetime as dt
    text = " ".join(str(l.get("text") or "") for l in design.get("layers") or [] if isinstance(l, dict) and l.get("type") == "text")
    text = re.sub(r"\s+", " ", text.lower())
    years = re.findall(r"\b(20\d\d)\b", text)
    default_year = int(years[0]) if years else dt.date.today().year
    patterns = [
        # Friday 15 November 2026 / Fri, 15th Nov
        rf"\b{WEEKDAY_RE},?\s+(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?{MONTH_RE}(?:,?\s+(20\d\d))?",
        # Friday, November 15, 2026 / Fri Nov 15th
        rf"\b{WEEKDAY_RE},?\s+{MONTH_RE}\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(20\d\d))?",
    ]
    issues = []
    for index, pattern in enumerate(patterns):
        for m in re.finditer(pattern, text):
            if index == 0:
                weekday, day, month, year = m.group(1), m.group(2), m.group(3), m.group(4)
            else:
                weekday, month, day, year = m.group(1), m.group(2), m.group(3), m.group(4)
            month_no = next((i + 1 for i, name in enumerate(MONTHS) if name.startswith(month[:3])), 0)
            try:
                actual = dt.date(int(year or default_year), month_no, int(day))
            except ValueError:
                continue
            named = next(name for name in WEEKDAYS if name.startswith(weekday[:3]))
            if WEEKDAYS[actual.weekday()] != named:
                issues.append(f"\"{m.group(0).strip()}\" — {actual.strftime('%d %B %Y')} is a {WEEKDAYS[actual.weekday()].title()}, not a {named.title()}.")
    return issues


def decorative_effect_count(design: dict[str, Any]) -> int:
    count = 0
    for l in design.get("layers") or []:
        if not isinstance(l, dict):
            continue
        if float(l.get("shadow_opacity") or 0) > 0:
            count += 1
        if float(l.get("text_stroke_width") or 0) > 0 or float(l.get("stroke_width") or 0) > 0:
            count += 1
        if l.get("fill") == "linear":
            count += 1
    return count


def design_quality_summary(design: dict[str, Any]) -> dict[str, Any]:
    layers = design.get("layers") or []
    text_layers = [l for l in layers if isinstance(l, dict) and l.get("type") == "text"]
    fonts = sorted({str(l.get("font") or "system-ui") for l in text_layers})
    colours = sorted({str(l.get("color")) for l in layers if isinstance(l, dict) and l.get("color")})
    canvas_bg = str((design.get("canvas") or {}).get("bg") or "#FFFFFF")
    low_contrast = []
    for l in text_layers:
        # This is a conservative canvas-background check. When text is over a panel/image,
        # the model's own quality gate remains responsible for local contrast.
        ratio = contrast_ratio(str(l.get("color") or "#111111"), canvas_bg)
        size = float(l.get("size") or 16)
        weight = int(l.get("weight") or 400)
        threshold = 3.0 if size >= 24 or (size >= 19 and weight >= 700) else 4.5
        if ratio < threshold:
            low_contrast.append({"name": l.get("name"), "ratio": round(ratio, 2), "threshold": threshold})
    score = 100
    if len(fonts) > 2:
        score -= min(18, (len(fonts) - 2) * 6)
    if len(colours) > 8:
        score -= min(12, (len(colours) - 8) * 2)
    score -= min(24, len(low_contrast) * 4)
    tiny = [l for l in text_layers if float(l.get("size") or 16) < 9]
    score -= min(16, len(tiny) * 4)
    # Restraint check: shadows/strokes/gradients piling up is the clearest "template" tell.
    effects = decorative_effect_count(design)
    if effects > 4:
        score -= min(15, (effects - 4) * 3)
    dates = date_conflicts(design)
    score -= min(20, len(dates) * 10)
    return {
        "score": max(0, score),
        "font_families": fonts,
        "colour_count": len(colours),
        "low_contrast_canvas_checks": low_contrast[:8],
        "tiny_text_layers": [l.get("name") for l in tiny[:8]],
        "decorative_effects": effects,
        "date_conflicts": dates,
    }


def canvas_for_format(fmt: str) -> tuple[int, int, str]:
    f = (fmt or "").lower()
    if "square" in f or "1080 × 1080" in f or "1080x1080" in f:
        return 432, 432, "1080 × 1080"
    if "story" in f or "1920" in f:
        return 432, 768, "1080 × 1920"
    if "a4" in f:
        return 432, 611, "A4"
    return 432, 540, "1080 × 1350"


def reconstruction_canvas(source_w: int, source_h: int) -> tuple[int, int]:
    if source_w <= 0 or source_h <= 0:
        return 432, 540
    max_w, max_h = 720, 540
    scale = min(max_w / source_w, max_h / source_h)
    return max(240, round(source_w * scale)), max(240, round(source_h * scale))


def normalise_crop(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    vals = [clamp_int(v, 0, 1000, 0) for v in value]
    left, top, right, bottom = vals
    if right <= left + 2 or bottom <= top + 2:
        return None
    return [left, top, right, bottom]


def normalise_design(
    payload: dict[str, Any],
    fmt: str | None = None,
    canvas_override: tuple[int, int] | None = None,
    allow_images: bool = False,
) -> dict[str, Any]:
    result = payload if isinstance(payload, dict) else {}
    raw_design = result.get("design") if isinstance(result.get("design"), dict) else result
    raw_canvas = raw_design.get("canvas") if isinstance(raw_design.get("canvas"), dict) else {}
    default_w, default_h, canonical_format = canvas_for_format(fmt or "")
    if canvas_override:
        default_w, default_h = canvas_override
        canonical_format = f"Source · {default_w} × {default_h}"
    width = clamp_int(raw_canvas.get("width"), 240, 900, default_w)
    height = clamp_int(raw_canvas.get("height"), 240, 1200, default_h)
    if canvas_override:
        width, height = default_w, default_h

    layers: list[dict[str, Any]] = []
    allowed_types = {"text", "shape", "image"} if allow_images else {"text", "shape"}
    for idx, raw in enumerate(raw_design.get("layers") or []):
        if not isinstance(raw, dict):
            continue
        layer_type = str(raw.get("type") or "shape").lower()
        if layer_type not in allowed_types:
            layer_type = "shape"
        layer: dict[str, Any] = {
            "type": layer_type,
            "name": str(raw.get("name") or f"Layer {idx + 1}")[:100],
            "x": clamp_int(raw.get("x"), -200, width + 100, 20),
            "y": clamp_int(raw.get("y"), -200, height + 100, 20),
            "w": clamp_int(raw.get("w"), 4, width + 300, 120),
            "h": clamp_int(raw.get("h"), 4, height + 300, 60),
            "opacity": clamp_float(raw.get("opacity"), 0.02, 1.0, 1.0),
            "rotation": clamp_float(raw.get("rotation"), -180.0, 180.0, 0.0),
        }
        if layer_type == "text":
            layer.update({
                "text": str(raw.get("text") or "Text")[:1200],
                "size": clamp_int(raw.get("size"), 6, 220, 28),
                "weight": clamp_int(raw.get("weight"), 200, 900, 600),
                "color": safe_hex(raw.get("color"), "#111111"),
                "spacing": clamp_float(raw.get("spacing"), -5.0, 20.0, 0.0),
                "line": clamp_float(raw.get("line"), 0.65, 2.4, 1.05),
                "font": safe_font(raw.get("font")),
                "align": str(raw.get("align") or "left").lower() if str(raw.get("align") or "left").lower() in {"left", "center", "right"} else "left",
                "text_stroke_color": safe_hex(raw.get("text_stroke_color"), "#000000"),
                "text_stroke_width": clamp_float(raw.get("text_stroke_width"), 0.0, 8.0, 0.0),
                "shadow_color": safe_hex(raw.get("shadow_color"), "#000000"),
                "shadow_opacity": clamp_float(raw.get("shadow_opacity"), 0.0, 0.9, 0.0),
                "shadow_x": clamp_float(raw.get("shadow_x"), -40.0, 40.0, 0.0),
                "shadow_y": clamp_float(raw.get("shadow_y"), -40.0, 40.0, 6.0),
                "shadow_blur": clamp_float(raw.get("shadow_blur"), 0.0, 80.0, 18.0),
            })
        elif layer_type == "shape":
            layer.update({
                "kind": safe_choice(raw.get("kind"), {"rect", "ellipse", "pill", "line", "triangle"}, "rect"),
                "fill": safe_choice(raw.get("fill"), {"solid", "linear"}, "solid"),
                "color": safe_hex(raw.get("color"), "#4E5DFF"),
                "color2": safe_hex(raw.get("color2"), safe_hex(raw.get("color"), "#4E5DFF")),
                "gradient_angle": clamp_float(raw.get("gradient_angle"), 0.0, 360.0, 135.0),
                "radius": safe_radius(raw.get("radius"), "0"),
                "stroke_color": safe_hex(raw.get("stroke_color"), "#000000"),
                "stroke_width": clamp_float(raw.get("stroke_width"), 0.0, 20.0, 0.0),
                "shadow_color": safe_hex(raw.get("shadow_color"), "#000000"),
                "shadow_opacity": clamp_float(raw.get("shadow_opacity"), 0.0, 0.8, 0.0),
                "shadow_x": clamp_float(raw.get("shadow_x"), -60.0, 60.0, 0.0),
                "shadow_y": clamp_float(raw.get("shadow_y"), -60.0, 60.0, 10.0),
                "shadow_blur": clamp_float(raw.get("shadow_blur"), 0.0, 100.0, 24.0),
            })
        else:
            crop = normalise_crop(raw.get("crop"))
            if crop:
                layer["crop"] = crop
            source_kind = safe_choice(raw.get("source_kind"), {"source", "ai", "local", "online"}, "source" if crop else "ai")
            layer["source_kind"] = source_kind
            if source_kind == "source":
                layer["asset"] = "source_upload"
            elif raw.get("asset"):
                layer["asset"] = str(raw.get("asset"))[:120]
            if raw.get("src"):
                layer["src"] = str(raw.get("src"))[:200000]
            if raw.get("asset_prompt"):
                layer["asset_prompt"] = str(raw.get("asset_prompt"))[:1500]
            layer["radius"] = safe_radius(raw.get("radius"), "0")
            layer["fit"] = safe_choice(raw.get("fit"), {"cover", "contain"}, "cover")
            layer["blend_mode"] = safe_choice(raw.get("blend_mode"), {"normal", "multiply", "screen", "overlay", "soft-light"}, "normal")
            layer["mask"] = safe_choice(raw.get("mask"), {"none", "fade-bottom", "fade-left", "fade-right", "soft-ellipse"}, "none")
            layer["brightness"] = clamp_float(raw.get("brightness"), 0.2, 2.0, 1.0)
            layer["contrast"] = clamp_float(raw.get("contrast"), 0.2, 2.0, 1.0)
            layer["saturation"] = clamp_float(raw.get("saturation"), 0.0, 2.0, 1.0)
            layer["blur"] = clamp_float(raw.get("blur"), 0.0, 20.0, 0.0)
        layers.append(layer)

    if not layers:
        layers = [
            {"type": "text", "name": "Headline", "x": 36, "y": 150, "w": 350, "h": 120, "text": "YOUR IDEA\nDESIGNED", "size": 52, "weight": 850, "color": "#FFFFFF", "spacing": 0, "line": 0.9, "font": "Arial Black", "align": "left", "opacity": 1, "rotation": 0},
            {"type": "text", "name": "Details", "x": 36, "y": 420, "w": 340, "h": 40, "text": "Add your details", "size": 16, "weight": 600, "color": "#FFFFFF", "spacing": 0, "line": 1.05, "font": "Arial", "align": "left", "opacity": 1, "rotation": 0},
        ]

    raw_palette = raw_design.get("palette") if isinstance(raw_design.get("palette"), dict) else {}
    palette = {
        "strategy": safe_choice(raw_palette.get("strategy"), {"monochromatic", "analogous", "complementary", "split-complementary", "triadic"}, "complementary"),
        "dominant": safe_hex(raw_palette.get("dominant"), safe_hex(raw_canvas.get("bg"), "#1F2445")),
        "support": safe_hex(raw_palette.get("support"), "#F2F2EE"),
        "accent": safe_hex(raw_palette.get("accent"), "#F4C95D"),
        "light": safe_hex(raw_palette.get("light"), "#FFFFFF"),
        "dark": safe_hex(raw_palette.get("dark"), "#111111"),
    }
    design = {
        "name": str(result.get("name") or raw_design.get("name") or "Untitled design")[:190],
        "format": canonical_format,
        "canvas": {"width": width, "height": height, "bg": safe_hex(raw_canvas.get("bg"), "#1F2445")},
        "palette": palette,
        "layers": layers[:40],
    }
    design["quality"] = design_quality_summary(design)
    return design



def closest_image_ratio(width: int, height: int) -> str:
    ratio = width / max(1, height)
    choices = {"1:1": 1.0, "2:3": 2/3, "3:2": 3/2, "3:4": .75, "4:3": 4/3, "4:5": .8, "5:4": 1.25, "9:16": 9/16, "16:9": 16/9}
    return min(choices, key=lambda k: abs(choices[k] - ratio))


def generate_image_asset(prompt: str, width: int = 1024, height: int = 1024) -> str:
    """Generate one visual asset. Typography/layout stays in structured Clyp layers."""
    if not prompt.strip():
        raise RuntimeError("Image prompt is required")
    if types is None:
        raise RuntimeError("google-genai is not installed. Run: py -m pip install -r requirements.txt")
    art_prompt = (
        "Create ONLY the visual asset for a professional graphic design, with no poster layout, no headline, no captions, "
        "no logo and no UI. Make it compositionally useful inside a flyer. "
        "It must look like genuine photography taken by a skilled human photographer at a real event or editorial shoot, "
        "not like AI art: natural skin texture and pores, real wardrobe with creases, candid unposed expressions, "
        "imperfect natural framing, a real lens with shallow depth of field, one motivated light source, subtle film grain, "
        "and a restrained, slightly warm colour grade. Subjects share one consistent environment and light. "
        "Avoid: airbrushed or plastic skin, perfect symmetry, heavenly light rays, halos, lens-flare stacks, glowing outlines, "
        "glossy CGI sheen, oversaturated royal-blue-and-gold fantasy colour, floating clouds, doves or crosses unless asked for, "
        "duplicated faces in crowds, extra fingers, and any written text. Asset brief: " + prompt.strip()
    )
    last_error: Exception | None = None
    models = [IMAGE_MODEL] + ([IMAGE_FALLBACK_MODEL] if IMAGE_FALLBACK_MODEL != IMAGE_MODEL else [])
    for model_name in models:
        client = get_client()
        try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[art_prompt],
                    config=types.GenerateContentConfig(
                        response_modalities=["IMAGE"],
                        response_format={"image": {"aspect_ratio": closest_image_ratio(width, height), "image_size": "1K"}},
                    ),
                )
            except (TypeError, ValueError):
                response = client.models.generate_content(
                    model=model_name,
                    contents=[art_prompt],
                    config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
                )
            for part in response.parts or []:
                blob = getattr(part, "inline_data", None)
                if blob is None:
                    continue
                data = getattr(blob, "data", None)
                mime = getattr(blob, "mime_type", None) or "image/png"
                if not data:
                    continue
                encoded = data if isinstance(data, str) else base64.b64encode(bytes(data)).decode("ascii")
                return f"data:{mime};base64,{encoded}"
            last_error = RuntimeError(f"{model_name} returned no image asset.")
        except Exception as exc:
            last_error = exc
        finally:
            client.close()
    raise RuntimeError(f"Image generation failed: {last_error}")


def hydrate_generated_assets(design: dict[str, Any], max_assets: int = 1) -> list[str]:
    assets = design.setdefault("assets", {})
    warnings: list[str] = []
    generated = 0
    for idx, layer in enumerate(design.get("layers") or []):
        if generated >= max_assets or not isinstance(layer, dict) or layer.get("type") != "image":
            continue
        prompt = str(layer.get("asset_prompt") or "").strip()
        if not prompt:
            continue
        key = f"ai_asset_{generated + 1}"
        try:
            assets[key] = generate_image_asset(prompt, int(layer.get("w") or 432), int(layer.get("h") or 540))
            layer["asset"] = key
            layer["source_kind"] = "ai"
            layer.pop("src", None)
            generated += 1
        except Exception as exc:
            warnings.append(f"Image asset could not be generated: {exc}")
    return warnings


IMAGERY_REQUIRED_PATTERNS = (
    "realistic image", "realistic photo", "photograph", "photography", "photo of",
    "image of", "picture of", "portrait of", "people", "person", "worshipper",
    "worshippers", "model", "product photo", "product shot", "food photo",
    "illustration", "illustrated", "3d render", "render of", "hero image",
    "background image", "cinematic", "editorial image", "lifestyle image",
)


def brief_requests_imagery(brief: str) -> bool:
    text = re.sub(r"\s+", " ", (brief or "").lower())
    return any(token in text for token in IMAGERY_REQUIRED_PATTERNS)


def dominant_text_side(design: dict[str, Any]) -> str:
    width = max(1, int(design.get("canvas", {}).get("width", 432)))
    text_layers = [l for l in design.get("layers", []) if isinstance(l, dict) and l.get("type") == "text"]
    if not text_layers:
        return "left"
    weighted = []
    for l in text_layers:
        x = float(l.get("x") or 0)
        w = float(l.get("w") or 80)
        size = float(l.get("size") or 16)
        weighted.append(((x + w / 2) / width, max(1.0, size)))
    avg = sum(pos * weight for pos, weight in weighted) / sum(weight for _, weight in weighted)
    if avg < .46:
        return "left"
    if avg > .54:
        return "right"
    return "center"


def build_fallback_asset_prompt(brief: str, design: dict[str, Any]) -> str:
    palette = design.get("palette") or {}
    copy_side = dominant_text_side(design)
    subject_side = "right" if copy_side == "left" else "left" if copy_side == "right" else "center/right"
    dark = palette.get("dark") or design.get("canvas", {}).get("bg") or "#17100f"
    accent = palette.get("accent") or "#d6a62a"
    dominant = palette.get("dominant") or dark
    return (
        f"Create the hero visual required by this design brief: {brief}. "
        f"This is a visual asset only, never a finished flyer. Place the main subject toward the {subject_side} "
        f"and preserve useful negative space on the {copy_side} for editable typography. "
        f"Art-direct the scene around a sophisticated palette related to {dominant}, {dark}, and accent {accent}. "
        "Shoot it like real event or editorial photography: one motivated light source, depth and foreground/background "
        "separation, natural skin and material texture, candid expression, subtle film grain and a restrained grade. "
        "Not polished stock, not CGI, no glow effects or light rays. "
        "No words, no captions, no logo, no poster layout, no decorative text, no UI."
    )


def ensure_required_hero_image(design: dict[str, Any], brief: str) -> tuple[bool, list[str]]:
    """Guarantee a hero image when the user's brief explicitly asks for imagery.

    Returns (required, warnings). Required imagery fails loudly instead of silently
    degrading into a typography-only design.
    """
    required = brief_requests_imagery(brief)
    image_layers = [l for l in design.get("layers", []) if isinstance(l, dict) and l.get("type") == "image"]

    # If the planner understood the request, hydrate its own image layer first.
    if image_layers:
        warnings = hydrate_generated_assets(design, max_assets=1)
        hydrated = any(l.get("type") == "image" and (l.get("asset") or l.get("src")) for l in design.get("layers", []))
        if required and not hydrated:
            detail = warnings[0] if warnings else "The required visual asset was not returned by the image model."
            raise RuntimeError(detail)
        return required, warnings

    if not required:
        return False, []

    canvas = design.get("canvas") or {}
    width = max(128, int(canvas.get("width") or 432))
    height = max(128, int(canvas.get("height") or 540))
    prompt = build_fallback_asset_prompt(brief, design)
    try:
        data_url = generate_image_asset(prompt, width, height)
    except Exception as exc:
        raise RuntimeError(
            "This brief requires a hero image, but Clyp could not generate it. "
            f"Image model error: {exc}"
        ) from exc

    hero = {
        "type": "image", "name": "AI hero image",
        "x": 0, "y": 0, "w": width, "h": height,
        "opacity": 1, "rotation": 0, "src": data_url,
        "source_kind": "ai", "asset_prompt": prompt,
        "fit": "cover", "blend_mode": "normal", "mask": "none",
        "brightness": .74, "contrast": 1.12, "saturation": 1.06, "blur": 0,
        "focal_x": 68 if dominant_text_side(design) == "left" else 32 if dominant_text_side(design) == "right" else 55,
        "focal_y": 50, "radius": "0"
    }
    # Back-to-front layer order: hero must sit beneath all editable typography/shapes.
    design.setdefault("layers", []).insert(0, hero)
    return True, []


def call_json(contents: Any, system_instruction: str, output_rules: str, temperature: float = 0.35) -> dict[str, Any]:
    client = get_client()
    if types is None:
        raise RuntimeError("google-genai is not installed. Run: py -m pip install -r requirements.txt")
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=f"{system_instruction}\n\n{output_rules}",
                response_mime_type="application/json",
                temperature=temperature,
                max_output_tokens=12288,
                thinking_config=types.ThinkingConfig(thinking_budget=0),
            ),
        )
        return parse_json_response(response.text or "")
    finally:
        client.close()


SYSTEM_DESIGNER = f"""You are Clyp's senior graphic designer and art director working inside an editable design editor.
Your job is to create professional, visually distinctive flyers/posters for non-designers while keeping every practical element editable.
Do not default to a generic SaaS/AI aesthetic. Match the design language to the audience, message and category.

{DESIGN_PLAYBOOK}

{FEW_SHOT_PATTERNS}

Every returned layer must be independently editable. Keep coordinates inside the canvas unless an intentional bleed is required.
Never invent critical factual information. If important facts are missing, use clearly neutral placeholders or omit them.
"""

SYSTEM_RECONSTRUCTOR = """You are Clyp's forensic flyer reconstruction engine. Your task is visual tracing, not redesign.
Study the uploaded source carefully and preserve its original composition, aspect ratio, hierarchy, palette, spacing, scale relationships and visual weight. Do NOT simplify a rich design into a generic poster. Do NOT improve or modernise the source. Match it.
Complex source imagery must be preserved as cropped image layers from the original upload rather than replaced with crude vector approximations. Photographs, faces, logos, icons, lighting rigs, glow effects, textured brush marks and detailed decorative graphics should normally become image crop layers. Text that is meant to be editable should become text layers with exact transcription and close typography/placement. Simple solid bars and blocks may become shapes.
The final layer stack must visually resemble the uploaded source before the user edits anything."""


@app.post("/generate")
def generate():
    if not authorised(request):
        return jsonify({"ok": False, "message": "unauthorised"}), 401
    started = time.perf_counter()
    try:
        data = request.get_json(force=True) or {}
        brief = str(data.get("brief") or "").strip()
        fmt = str(data.get("format") or "Instagram portrait · 1080 × 1350")
        if not brief:
            return jsonify({"ok": False, "message": "Brief is required"}), 422
        width, height, canonical = canvas_for_format(fmt)
        prompt = f"""<context>
User brief: {brief}
Working canvas: {width} by {height} editor units.
Intended export format: {canonical}.
</context>
<task>
Create a complete, professionally art-directed editable flyer/poster. Infer the category and mood from the brief. Build the hierarchy, palette, typography and composition deliberately. If the user explicitly asks for a photograph, realistic image, people, a model, product photography, illustration, or another hero visual, you MUST include one image layer with a precise asset_prompt; imagery is not optional in that case. Use gradients/shapes/effects only when they perform a visual job. Use concise real copy inferred from the brief; if a critical fact such as date, price, time, venue, phone or URL was not supplied, use a neutral placeholder or omit it rather than inventing facts.
</task>
<quality_gate>
Before output, silently review the result at full size and thumbnail size for hierarchy, colour harmony, text contrast, margins, alignment, proximity, balance, readability and unnecessary decoration.
</quality_gate>"""
        raw = call_json(prompt, SYSTEM_DESIGNER, DESIGN_OUTPUT_RULES, temperature=0.45)
        design = normalise_design(raw, fmt, allow_images=True)
        imagery_required, warnings = ensure_required_hero_image(design, brief)
        # Re-run the local quality summary after the image is hydrated/inserted.
        design["quality"] = design_quality_summary(design)
        warnings += [f"Check the date: {issue}" for issue in design["quality"]["date_conflicts"]]
        return jsonify({"ok": True, "model": MODEL, "image_model": IMAGE_MODEL, "design": design, "critique": raw.get("critique", {}), "warnings": warnings, "imagery_required": imagery_required, "duration_ms": int((time.perf_counter() - started) * 1000)})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502


@app.post("/edit")
def edit():
    if not authorised(request):
        return jsonify({"ok": False, "message": "unauthorised"}), 401
    started = time.perf_counter()
    try:
        data = request.get_json(force=True) or {}
        command = str(data.get("command") or "").strip()
        current = data.get("design")
        if not command or not isinstance(current, dict):
            return jsonify({"ok": False, "message": "Command and current design are required"}), 422
        fmt = str(current.get("format") or data.get("format") or "1080 × 1350")
        prompt = (
            "Modify the existing editable design according to the user's instruction. Preserve everything that does not need to change. "
            "Image layers may reference asset='source_upload'; preserve those layers unless the user asks to remove or move them. Return the full revised editable design.\n\n"
            f"User instruction: {command}\n\nExisting design JSON:\n{json.dumps(current, ensure_ascii=False)}"
        )
        current_images = [l for l in current.get("layers", []) if isinstance(l, dict) and l.get("type") == "image"]
        source_trace = any(l.get("crop") or l.get("source_kind") == "source" for l in current_images)
        raw = call_json(prompt, SYSTEM_DESIGNER, RECONSTRUCTION_OUTPUT_RULES if source_trace else DESIGN_OUTPUT_RULES)
        design = normalise_design(raw, fmt, canvas_override=(int(current.get("canvas", {}).get("width", 432)), int(current.get("canvas", {}).get("height", 540))) if source_trace else None, allow_images=True)
        # The layout model should not have to echo large URLs/base64 assets. Reattach image
        # identity from the current structured design by name/order whenever it preserved an image.
        old_by_name = {str(l.get("name") or ""): l for l in current_images}
        old_remaining = list(current_images)
        for layer in design.get("layers", []):
            if layer.get("type") != "image":
                continue
            old = old_by_name.get(str(layer.get("name") or ""))
            if old is None and old_remaining:
                old = old_remaining.pop(0)
            if old:
                for key in ("asset", "src", "source_kind", "crop", "attribution", "asset_prompt"):
                    if old.get(key) is not None and not layer.get(key):
                        layer[key] = old.get(key)
        design["name"] = current.get("name") or design["name"]
        design["format"] = current.get("format") or design["format"]
        return jsonify({"ok": True, "model": MODEL, "design": design, "critique": raw.get("critique", {}), "duration_ms": int((time.perf_counter() - started) * 1000)})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502



@app.post("/image-generate")
def image_generate():
    if not authorised(request):
        return jsonify({"ok": False, "message": "unauthorised"}), 401
    started = time.perf_counter()
    try:
        data = request.get_json(force=True) or {}
        prompt = str(data.get("prompt") or "").strip()
        width = clamp_int(data.get("width"), 128, 4096, 1024)
        height = clamp_int(data.get("height"), 128, 4096, 1024)
        if not prompt:
            return jsonify({"ok": False, "message": "Image prompt is required"}), 422
        data_url = generate_image_asset(prompt, width, height)
        return jsonify({"ok": True, "model": IMAGE_MODEL, "data_url": data_url, "duration_ms": int((time.perf_counter() - started) * 1000)})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502


@app.post("/reconstruct")
def reconstruct():
    if not authorised(request):
        return jsonify({"ok": False, "message": "unauthorised"}), 401
    started = time.perf_counter()
    try:
        data = request.get_json(force=True) or {}
        data_url = str(data.get("data_url") or "")
        filename = str(data.get("filename") or "uploaded design")
        source_w = clamp_int(data.get("source_width"), 0, 10000, 0)
        source_h = clamp_int(data.get("source_height"), 0, 10000, 0)
        if not data_url.startswith("data:") or ";base64," not in data_url:
            return jsonify({"ok": False, "message": "A base64 data URL is required"}), 422
        header, encoded = data_url.split(",", 1)
        mime = header[5:].split(";", 1)[0].strip() or "image/png"
        blob = base64.b64decode(encoded, validate=True)
        if len(blob) > 7 * 1024 * 1024:
            return jsonify({"ok": False, "message": "File is too large for this local MVP (7 MB max)."}), 413
        if types is None:
            raise RuntimeError("google-genai is not installed. Run: py -m pip install -r requirements.txt")

        canvas_w, canvas_h = reconstruction_canvas(source_w, source_h)
        aspect_note = f"The source is {source_w}×{source_h} pixels. Use an exact proportional working canvas of {canvas_w}×{canvas_h} editor units." if source_w and source_h else f"Use a working canvas of {canvas_w}×{canvas_h} editor units."
        prompt = (
            "Reconstruct this uploaded flyer as faithfully as possible. This is a source-matching task, not a creative reinterpretation.\n"
            f"{aspect_note}\n"
            "First identify major photographic/graphic zones, then exact editable text, then simple shapes. "
            "Preserve the original dark/light regions, photo coverage, title proportions, footer structure, logos/icons and decorative effects. "
            "For every photo/logo/icon/complex visual region that should be preserved from the source, create an image layer with a crop=[left,top,right,bottom] box using 0..1000 normalised source coordinates and x/y/w/h showing where that crop belongs on the working canvas. "
            "Do not replace a photograph with a circle or a flat colour. Do not replace a logo with placeholder text if it can be retained as an image crop. "
            "Transcribe visible editable text exactly, including line breaks where they matter. Match condensed/bold typography using the closest allowed font. "
            "Use back-to-front layer order. Fidelity is more important than having few layers."
        )
        raw = call_json([prompt, types.Part.from_bytes(data=blob, mime_type=mime)], SYSTEM_RECONSTRUCTOR, RECONSTRUCTION_OUTPUT_RULES, temperature=0.2)
        design = normalise_design(raw, canvas_override=(canvas_w, canvas_h), allow_images=True)
        design["name"] = Path(filename).stem[:190] or design["name"]
        design["format"] = f"Source · {source_w} × {source_h}" if source_w and source_h else f"Source · {canvas_w} × {canvas_h}"
        return jsonify({"ok": True, "model": MODEL, "design": design, "critique": raw.get("critique", {}), "duration_ms": int((time.perf_counter() - started) * 1000)})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502


TRANSCRIBE_OUTPUT_RULES = r"""
Return ONLY one JSON object. Do not use Markdown or code fences.
{
  "text": "complete punctuated transcript in chronological order",
  "segments": [{"start": 0.0, "end": 2.4, "text": "exact spoken words for this segment"}]
}
Times are seconds from the start of this audio clip. Segments are chronological, do not overlap,
and are short: one phrase or sentence, ideally under four seconds each.
In each segment's text, wrap the one word a viewer should notice most in asterisks, e.g.
"*angels* still walk this earth," - at most one emphasised word per four or five words. Never
put asterisks in the top-level "text".
"""

SYSTEM_TRANSCRIBER = """You are Clyp's caption transcriber. You produce accurate, verbatim transcripts with precise timings for burned-in video captions.
Preserve the spoken language and wording; do not summarise, translate or correct grammar. Add natural punctuation. Ignore music and non-speech sounds."""


def seconds_value(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        parts = [float(p) for p in text.split(":")]
    except ValueError:
        return 0.0
    if len(parts) == 3:
        return max(0.0, parts[0] * 3600 + parts[1] * 60 + parts[2])
    if len(parts) == 2:
        return max(0.0, parts[0] * 60 + parts[1])
    return max(0.0, parts[0])


@app.post("/transcribe")
def transcribe():
    if not authorised(request):
        return jsonify({"ok": False, "message": "unauthorised"}), 401
    started = time.perf_counter()
    try:
        data = request.get_json(force=True) or {}
        mime = str(data.get("mime") or "audio/mp3")
        duration = clamp_float(data.get("duration"), 0, 7200, 0)
        previous = re.sub(r"\s+", " ", str(data.get("previous") or "")).strip()[-500:]
        blob = base64.b64decode(str(data.get("audio_b64") or ""), validate=True)
        if not blob:
            return jsonify({"ok": False, "message": "Audio is required"}), 422
        # Gemini inline requests are capped at 20 MB including base64 overhead.
        if len(blob) > 14 * 1024 * 1024:
            return jsonify({"ok": False, "message": "This audio chunk is too large. Lower CLYP_TRANSCRIBE_CHUNK_SECONDS in .env."}), 413
        if types is None:
            raise RuntimeError("google-genai is not installed. Run: py -m pip install -r requirements.txt")

        language = (os.getenv("CLYP_TRANSCRIBE_LANGUAGE") or os.getenv("GEMINI_LANGUAGE") or "auto").strip()
        prompt = "Transcribe all spoken words in this audio clip with start and end times in seconds relative to the clip."
        if language and language.lower() != "auto":
            prompt += f" Expect the language to be {language}."
        else:
            prompt += " Detect the language automatically."
        if previous:
            prompt += f" The previous clip ended with: \"{previous}\". Use it only to resolve a cut-off word; do not repeat it."
        raw = call_json([prompt, types.Part.from_bytes(data=blob, mime_type=mime)], SYSTEM_TRANSCRIBER, TRANSCRIBE_OUTPUT_RULES, temperature=0.0)

        segments = []
        for item in raw.get("segments") or []:
            if not isinstance(item, dict):
                continue
            text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
            if not text:
                continue
            start = seconds_value(item.get("start"))
            end = seconds_value(item.get("end"))
            if duration > 0:
                start = min(max(0.0, duration - 0.1), start)
                end = min(duration, end)
            end = max(start + 0.2, end)
            segments.append({"start": round(start, 3), "end": round(end, 3), "text": text})
        segments.sort(key=lambda s: s["start"])
        text = str(raw.get("text") or "").strip() or " ".join(s["text"] for s in segments)
        if not segments and text:
            segments.append({"start": 0.0, "end": round(max(0.5, duration), 3), "text": text})
        return jsonify({"ok": True, "model": MODEL, "text": text, "segments": segments, "duration_ms": int((time.perf_counter() - started) * 1000)})
    except Exception as exc:
        return jsonify({"ok": False, "message": str(exc)}), 502


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "clyp-ai",
        "python": True,
        "model": MODEL,
        "image_model": IMAGE_MODEL,
        "image_fallback_model": IMAGE_FALLBACK_MODEL,
        "gemini_configured": bool(API_KEY),
        "sdk_installed": genai is not None,
        "structured_output": "json-mime/no-response-schema",
        "thinking_budget": 0,
        "reconstruction": "source-aspect + editable text/shapes + source image crops",
        "design_brain": "professional-art-director-v4",
        "advanced_shapes": True,
        "generated_image_assets": True,
        "image_compositing": True,
        "transcription": True,
    })


if __name__ == "__main__":
    parsed = urlparse(AI_ENDPOINT if "://" in AI_ENDPOINT else f"http://{AI_ENDPOINT}")
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8100
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)
