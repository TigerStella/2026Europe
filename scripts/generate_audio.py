"""도슨트 음성 일괄 생성 스크립트 (edge-tts, 남성 InJoon)

사용법:
  pip install edge-tts
  python scripts/generate_audio.py data/docent_paris_orsay_orangerie.json
  python scripts/generate_audio.py data/*.json --force   # 기존 파일 덮어쓰기

출력: audio/{museumId}/intro.mp3, audio/{museumId}/{workId}_{track}.mp3
      audio/manifest.json (오프라인 캐시 목록)
"""
import asyncio
import glob
import json
import sys
from pathlib import Path

import edge_tts

VOICE = "ko-KR-InJoonNeural"
RATE = "-5%"      # 아이가 듣기 편하도록 살짝 느리게
OUT = Path("audio")


async def synth(text: str, path: Path, force: bool) -> bool:
    if path.exists() and path.stat().st_size > 0 and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        try:
            await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(path))
            if path.stat().st_size == 0:
                raise RuntimeError("빈 파일")
            return True
        except Exception as e:  # 네트워크 일시 오류 재시도
            print(f"  재시도 {attempt + 1}/3: {path.name} ({e})")
            await asyncio.sleep(2)
    raise RuntimeError(f"생성 실패: {path}")


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    files = [f for pattern in args for f in glob.glob(pattern)]
    if not files:
        sys.exit("JSON 경로를 지정하세요")

    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}

    for f in files:
        data = json.loads(Path(f).read_text("utf-8"))
        for m in data["museums"]:
            mid = m["id"]
            paths = []
            jobs = []
            if m.get("intro", {}).get("script"):
                p = OUT / mid / "intro.mp3"
                jobs.append((m["intro"]["script"], p))
            for w in m["works"]:
                for track, text in w.get("audioScripts", {}).items():
                    if text.strip():
                        jobs.append((text, OUT / mid / f"{w['id']}_{track}.mp3"))
            for text, p in jobs:
                made = await synth(text, p, force)
                print(("생성 " if made else "건너뜀 ") + str(p))
                paths.append(str(p).replace("\\", "/"))
            manifest[mid] = paths

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    total = sum(len(v) for v in manifest.values())
    print(f"완료: {total}개 파일, manifest → {manifest_path}")


if __name__ == "__main__":
    asyncio.run(main())
