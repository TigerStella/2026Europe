"""특별전 오디오 가이드 음성 생성 (edge-tts) — data/special_*.json 전용

museumId.clips[].text를 clip별 mp3 한 개로 합성한다. 문장 단위 합성·휴지·텍스트 정리는
generate_audio.py의 함수를 그대로 가져다 쓴다(복사 금지, import로 재사용).
voice·rate는 각 JSON 최상위 값을 쓴다(기존 docent_*.json의 고정 보이스와 무관).

사용법:
  python scripts/generate_special_audio.py data/special_*.json           # 없는 파일만 생성
  python scripts/generate_special_audio.py data/special_*.json --force   # 전부 다시 생성

출력: audio/{museumId}/{clipId}.mp3, audio/manifest.json의 {museumId} 키(다른 박물관 키는 보존)
"""
import asyncio
import glob
import json
import sys
from pathlib import Path

from generate_audio import synth_track, require_ffmpeg, VOICE as DEFAULT_VOICE, RATE as DEFAULT_RATE, CONCURRENCY

OUT = Path("audio")


async def run_all(files: list[str], force: bool) -> None:
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    sem = asyncio.Semaphore(CONCURRENCY)
    made = skipped = failed = 0
    fail_ids: list[str] = []

    async def job(mid: str, clip_id: str, text: str, voice: str, rate: str, p: Path) -> None:
        nonlocal made, skipped, failed
        if p.exists() and p.stat().st_size > 0 and not force:
            skipped += 1
            print("건너뜀 " + str(p))
            return
        async with sem:
            try:
                n = await synth_track(text, p, voice, rate)
                made += 1
                print(f"생성 {p} ({n}문장)")
            except Exception as e:
                failed += 1
                fail_ids.append(f"{mid}/{clip_id}")
                print(f"실패 {p}: {e}")

    for f in files:
        data = json.loads(Path(f).read_text("utf-8"))
        mid = data["museumId"]
        voice = data.get("voice") or DEFAULT_VOICE
        rate = data.get("rate") or DEFAULT_RATE
        jobs = []
        for c in data.get("clips", []):
            text = (c.get("text") or "").strip()
            if not text:
                continue
            jobs.append((c["id"], text, OUT / mid / f"{c['id']}.mp3"))
        await asyncio.gather(*(job(mid, cid, text, voice, rate, p) for cid, text, p in jobs))
        manifest[mid] = [str(p).replace("\\", "/") for _, _, p in jobs]

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    total = sum(len(v) for v in manifest.values())
    print(f"완료: 생성 {made} · 건너뜀 {skipped} · 실패 {failed} · manifest 총 {total}개 → {manifest_path}")
    if fail_ids:
        print("실패 클립: " + ", ".join(fail_ids))


async def main() -> None:
    require_ffmpeg()
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    files = sorted({f for pattern in args for f in glob.glob(pattern)})
    if not files:
        sys.exit("JSON 경로를 지정하세요 (예: data/special_*.json)")
    await run_all(files, force)


if __name__ == "__main__":
    asyncio.run(main())
