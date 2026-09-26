"""도슨트 음성 일괄 생성 스크립트 (edge-tts)

자연스럽게 들리도록
  1) 읽기 전 텍스트 다듬기: 「」『』·따옴표 제거, 줄표(—)→쉼표, "1300~1305년"→"1300년에서 1305년",
     괄호→앞뒤 쉼표
  2) 문장 단위로 따로 합성한 뒤, 문장 사이 0.3초(물음표 뒤 0.45초) 무음을 넣어 mp3 하나로 이어 붙임
     (긴 글을 한 번에 읽히면 억양이 평평하고 숨 쉴 틈이 없음)

사용법:
  pip install edge-tts        # ffmpeg도 필요(이어 붙이기용)
  python scripts/generate_audio.py data/docent_*.json           # 없는 파일만 생성
  python scripts/generate_audio.py data/docent_*.json --force   # 전부 다시 생성
  python scripts/generate_audio.py --samples                    # 목소리 비교 샘플(audio/_samples/)

출력(경로·이름 규칙 고정): audio/{museumId}/intro.mp3, audio/{museumId}/{workId}_{track}.mp3,
      audio/manifest.json  ← 앱이 읽는 음성 목록 { museumId: [경로, …] }
"""
import asyncio
import glob
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import edge_tts

# ── 목소리 설정(샘플 비교 후 고른 값으로 고정: 3번 현수 · 기본 속도) ──
VOICE = "ko-KR-HyunsuMultilingualNeural"
RATE = "+0%"
PAUSE_SENTENCE = 0.30   # 문장 사이 무음(초)
PAUSE_QUESTION = 0.45   # 물음표 뒤 무음(초)
SAMPLE_RATE = 24000     # edge-tts 기본 출력과 동일
BITRATE = "48k"
CONCURRENCY = 3         # 동시에 만드는 트랙 수(서버 부담·차단 방지)

OUT = Path("audio")
SAMPLE_DIR = OUT / "_samples"
SAMPLE_SOURCE = "data/docent_florence_uffizi.json"   # 우피치 인트로 대본으로 비교
SAMPLE_VARIANTS = [
    ("1_injoon_minus5", "ko-KR-InJoonNeural", "-5%"),
    ("2_injoon_0", "ko-KR-InJoonNeural", "+0%"),
    ("3_hyunsu_0", "ko-KR-HyunsuMultilingualNeural", "+0%"),
    ("4_hyunsu_minus5", "ko-KR-HyunsuMultilingualNeural", "-5%"),
]


# ── 1) 텍스트 다듬기 ──
def normalize(text: str) -> str:
    t = text
    t = re.sub(r"[「」『』“”‘’\"']", "", t)                                   # 따옴표류 제거
    t = re.sub(r"\s*[—–―]\s*", ", ", t)                                       # 줄표 → 쉼표
    t = re.sub(r"(\d[\d,]*)\s*[~∼〜～]\s*(\d[\d,]*)\s*(년|세기)", r"\1\3에서 \2\3", t)  # 1300~1305년 → 1300년에서 1305년
    t = re.sub(r"\s*\(([^()]*)\)\s*", r", \1, ", t)                            # (괄호) → , 괄호,
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(?:\s*,){2,}", ",", t)                                        # 쉼표 중복
    t = re.sub(r"\s*,\s*", ", ", t)
    t = re.sub(r",\s*([.!?…])", r"\1", t)                                      # 문장부호 앞 쉼표
    t = re.sub(r"^[\s,]+|[\s,]+$", "", t)
    return t.strip()


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+", normalize(text))
    return [p.strip() for p in parts if re.search(r"[가-힣A-Za-z0-9]", p)]


# ── 2) 문장별 합성 + 무음 넣어 이어 붙이기 ──
async def synth_sentence(text: str, path: Path, voice: str, rate: str) -> None:
    for attempt in range(4):
        try:
            await edge_tts.Communicate(text, voice, rate=rate).save(str(path))
            if path.stat().st_size == 0:
                raise RuntimeError("빈 파일")
            return
        except Exception as e:  # 네트워크 일시 오류 재시도
            print(f"  재시도 {attempt + 1}/4: {text[:20]}… ({e})")
            await asyncio.sleep(2 * (attempt + 1))
    raise RuntimeError(f"문장 합성 실패: {text[:30]}")


def join_with_pauses(parts: list[Path], pauses: list[float], out: Path) -> None:
    """각 문장 뒤에 무음을 붙여 하나의 mp3로(ffmpeg 한 번 호출)"""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for p in parts:
        cmd += ["-i", str(p)]
    chains, labels = [], []
    for i, pause in enumerate(pauses):
        pad = f",apad=pad_dur={pause}" if pause > 0 else ""
        chains.append(f"[{i}:a]aformat=sample_rates={SAMPLE_RATE}:channel_layouts=mono{pad}[a{i}]")
        labels.append(f"[a{i}]")
    graph = ";".join(chains) + ";" + "".join(labels) + f"concat=n={len(parts)}:v=0:a=1[out]"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_suffix(".tmp.mp3")
    cmd += ["-filter_complex", graph, "-map", "[out]", "-ac", "1", "-ar", str(SAMPLE_RATE),
            "-c:a", "libmp3lame", "-b:a", BITRATE, str(tmp_out)]
    subprocess.run(cmd, check=True)
    tmp_out.replace(out)


async def synth_track(text: str, out: Path, voice: str = VOICE, rate: str = RATE) -> int:
    sentences = split_sentences(text)
    if not sentences:
        raise RuntimeError(f"읽을 문장이 없음: {out}")
    with tempfile.TemporaryDirectory() as td:
        parts, pauses = [], []
        for i, s in enumerate(sentences):
            p = Path(td) / f"{i:03d}.mp3"
            await synth_sentence(s, p, voice, rate)
            parts.append(p)
            last = i == len(sentences) - 1
            pauses.append(0 if last else (PAUSE_QUESTION if s.endswith("?") else PAUSE_SENTENCE))
        join_with_pauses(parts, pauses, out)
    return len(sentences)


# ── 실행 ──
def require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg가 필요해요 (예: sudo apt-get install ffmpeg / brew install ffmpeg)")


async def run_samples() -> None:
    data = json.loads(Path(SAMPLE_SOURCE).read_text("utf-8"))
    script = data["museums"][0]["intro"]["script"]
    ok = 0
    for name, voice, rate in SAMPLE_VARIANTS:
        out = SAMPLE_DIR / f"{name}.mp3"
        try:
            n = await synth_track(script, out, voice, rate)
            print(f"샘플 생성 {out}  ({voice}, {rate}, {n}문장)")
            ok += 1
        except Exception as e:
            print(f"샘플 실패 {out}  ({voice}, {rate}): {e}")
    if ok == 0:
        sys.exit("샘플을 하나도 만들지 못했어요")


async def run_all(files: list[str], force: bool) -> None:
    manifest_path = OUT / "manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else {}
    sem = asyncio.Semaphore(CONCURRENCY)
    made = skipped = 0

    async def job(text: str, p: Path) -> None:
        nonlocal made, skipped
        if p.exists() and p.stat().st_size > 0 and not force:
            skipped += 1
            print("건너뜀 " + str(p))
            return
        async with sem:
            n = await synth_track(text, p)
        made += 1
        print(f"생성 {p} ({n}문장)")

    for f in files:
        data = json.loads(Path(f).read_text("utf-8"))
        for m in data["museums"]:
            mid = m["id"]
            jobs = []
            if m.get("intro", {}).get("script"):
                jobs.append((m["intro"]["script"], OUT / mid / "intro.mp3"))
            for w in m["works"]:
                for track, text in w.get("audioScripts", {}).items():
                    if text.strip():
                        jobs.append((text, OUT / mid / f"{w['id']}_{track}.mp3"))
            await asyncio.gather(*(job(t, p) for t, p in jobs))
            manifest[mid] = [str(p).replace("\\", "/") for _, p in jobs]

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    total = sum(len(v) for v in manifest.values())
    print(f"완료: 생성 {made} · 건너뜀 {skipped} · manifest 총 {total}개 → {manifest_path}")


async def main() -> None:
    require_ffmpeg()
    if "--samples" in sys.argv:
        await run_samples()
        return
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    files = sorted({f for pattern in args for f in glob.glob(pattern)})
    if not files:
        sys.exit("JSON 경로를 지정하세요")
    await run_all(files, force)


if __name__ == "__main__":
    asyncio.run(main())
