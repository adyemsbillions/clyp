from __future__ import annotations
import importlib.util
import os
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
for raw in (ROOT/'.env').read_text(encoding='utf-8').splitlines() if (ROOT/'.env').exists() else []:
    line=raw.strip()
    if line and not line.startswith('#') and '=' in line:
        k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"\''))

print('Clyp Fast Dev diagnostics')
print('Python:', 'OK')
print('Flask:', 'OK' if importlib.util.find_spec('flask') else 'MISSING')
print('google-genai:', 'OK' if importlib.util.find_spec('google.genai') else 'MISSING')
print('Gemini key:', 'configured' if (os.getenv('CLYP_GEMINI_API_KEY') or os.getenv('GEMINI_API_KEY')) else 'MISSING')
import shutil
ffmpeg=os.getenv('CLYP_FFMPEG_PATH') or os.getenv('FFMPEG_PATH') or 'ffmpeg'
print('FFmpeg (video editor):', 'OK' if (shutil.which(ffmpeg) or os.path.isfile(ffmpeg)) else 'MISSING')
print('Design model:', os.getenv('CLYP_GEMINI_MODEL','gemini-2.5-flash'))
print('Image model:', os.getenv('CLYP_GEMINI_IMAGE_MODEL','gemini-3.1-flash-image'))
print('Online assets: Openverse')
print('Storage: browser localStorage')
print('Accounts: disabled')
print('MySQL/XAMPP: not required')
for name,url in [('Web', os.getenv('CLYP_APP_URL','http://127.0.0.1:8080')+'/api/health'),('AI', os.getenv('CLYP_AI_ENDPOINT','http://127.0.0.1:8100')+'/health')]:
    try:
        with urllib.request.urlopen(url,timeout=1.5) as r:
            print(f'{name}: running ({r.status})')
    except Exception:
        print(f'{name}: not running')
