from pathlib import Path
import wave, math, struct, random
RATE=44100; DURATION=8
out=Path(__file__).resolve().parents[1]/'storage'/'sounds';out.mkdir(parents=True,exist_ok=True)
tracks={
 'cinematic-rise.wav':[(110,.22),(165,.13),(220,.08)],
 'focused-momentum.wav':[(130,.16),(195,.11),(260,.06)],
 'bright-steps.wav':[(220,.13),(330,.10),(440,.07)],
 'daylight-vlog.wav':[(196,.12),(247,.10),(294,.08)],
 'afro-pulse.wav':[(120,.16),(180,.09),(240,.07)],
 'digital-current.wav':[(150,.12),(300,.08),(600,.04)],
}
for name,tones in tracks.items():
    path=out/name
    if path.exists(): continue
    with wave.open(str(path),'w') as w:
        w.setnchannels(2);w.setsampwidth(2);w.setframerate(RATE)
        for i in range(RATE*DURATION):
            t=i/RATE; fade=min(1,t/.35,(DURATION-t)/.45)
            beat=(1 if (t*2)%1<.12 else .25)
            if 'afro' in name: beat=(1 if (t*3)%1<.09 else .22)
            if 'cinematic' in name: beat=.35+.65*(t/DURATION)
            val=sum(math.sin(2*math.pi*f*t)*a for f,a in tones)*fade*(.65+.35*beat)
            val+=math.sin(2*math.pi*55*t)*.05*beat*fade
            sample=max(-32767,min(32767,int(val*32767)))
            w.writeframesraw(struct.pack('<hh',sample,sample))
print('Original Clyp demo sounds are ready.')
