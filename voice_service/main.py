import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from io import BytesIO
from pathlib import Path


def _get_ffmpeg_exe() -> str:
    """Return path to ffmpeg binary, prioritizing system PATH, falling back to imageio_ffmpeg."""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _convert_to_wav(src_path: str, dst_path: str) -> None:
    """Normalize arbitrary browser-recorded audio (webm/opus, ogg, mp3, ...) to
    16kHz mono WAV, since soundfile/libsndfile can't read most of those directly."""
    ffmpeg_exe = _get_ffmpeg_exe()
    result = subprocess.run(
        [ffmpeg_exe, "-y", "-i", src_path, "-ar", "16000", "-ac", "1", dst_path],
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        logger.warning("ffmpeg failed to decode audio: %s", result.stderr.decode(errors="replace")[-500:])
        raise HTTPException(
            status_code=400,
            detail="Could not decode audio. Unsupported or corrupt file.",
        )

import edge_tts
import soundfile as sf
import torch
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from markdown import markdown
from pydantic import BaseModel
from transformers import AutoModel, AutoTokenizer

try:
    from parler_tts import ParlerTTSForConditionalGeneration
    HAS_PARLER = True
except ImportError:
    HAS_PARLER = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("voice_service")

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR.parent / ".env")
HF_TOKEN = os.environ.get("HF_TOKEN", "")
DEVICE = "cuda:0" if torch.cuda.is_available() else "cpu"
MODEL_DTYPE = torch.float16 if DEVICE.startswith("cuda") else torch.float32

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25MB
MAX_SPEAK_CHARS = 1000  # keeps generation time/VRAM bounded

app = FastAPI(title="Setu — Voice Service")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _gpu_mem_gb() -> str:
    if not torch.cuda.is_available():
        return "n/a"
    return f"{torch.cuda.memory_allocated(DEVICE)/1e9:.2f}GB alloc / {torch.cuda.memory_reserved(DEVICE)/1e9:.2f}GB reserved"


asr_model = None
tts_model = None
tts_tokenizer = None
tts_description_tokenizer = None
gpu_lock = threading.Lock()


def get_asr_model():
    global asr_model
    if asr_model is None:
        logger.info("Loading SraVaani-1.0 (device=%s, dtype=%s)...", DEVICE, MODEL_DTYPE)
        asr_model = AutoModel.from_pretrained(
            "ARTPARK-IISc/SraVaani-1.0", trust_remote_code=True, token=HF_TOKEN, torch_dtype=MODEL_DTYPE
        ).to(DEVICE).eval()
        logger.info("SraVaani-1.0 loaded. GPU memory: %s", _gpu_mem_gb())
    return asr_model


# Pre-warm ASR model in background thread
def _preload_asr():
    try:
        get_asr_model()
    except Exception as e:
        logger.warning("Background ASR preloading failed: %s", e)

threading.Thread(target=_preload_asr, daemon=True).start()


def get_tts_model():
    global tts_model, tts_tokenizer, tts_description_tokenizer
    if not HAS_PARLER:
        return None, None, None
    if tts_model is None:
        logger.info("Loading Indic Parler-TTS (device=%s, dtype=%s)...", DEVICE, MODEL_DTYPE)
        tts_model = ParlerTTSForConditionalGeneration.from_pretrained(
            "ai4bharat/indic-parler-tts", token=HF_TOKEN, torch_dtype=MODEL_DTYPE
        ).to(DEVICE).eval()
        tts_tokenizer = AutoTokenizer.from_pretrained("ai4bharat/indic-parler-tts", token=HF_TOKEN)
        tts_description_tokenizer = AutoTokenizer.from_pretrained(
            tts_model.config.text_encoder._name_or_path, token=HF_TOKEN
        )
        logger.info("Indic Parler-TTS loaded. GPU memory: %s", _gpu_mem_gb())
    return tts_model, tts_tokenizer, tts_description_tokenizer

DEFAULT_VOICE_DESCRIPTION = (
    "A female speaker delivers a clear, moderate-speed speech with a close "
    "recording and no background noise."
)

# Both models share one GPU with limited VRAM. Two requests running .generate()
# at the same time can race for memory and OOM, so inference is serialized here
# rather than left to FastAPI's default threadpool concurrency.
gpu_lock = threading.Lock()


class SpeakRequest(BaseModel):
    text: str
    description: str = DEFAULT_VOICE_DESCRIPTION


@app.get("/health")
def health_check():
    return {"status": "ok", "device": DEVICE, "gpu_memory": _gpu_mem_gb()}




_WHITESPACE_RE = re.compile(r"\s+")


def _markdown_to_speech_text(raw: str) -> str:
    """Strip markdown formatting so TTS doesn't try to "speak" **, |, #, etc.
    The frontend renders the original markdown for display — this only affects
    what actually gets synthesized."""
    html = markdown(raw, extensions=["tables"])
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    return _WHITESPACE_RE.sub(" ", text).strip()


# edge-tts needs an explicit voice (it doesn't auto-detect language like
# Parler-TTS does), so we pick one by scanning the text's Unicode script —
# the same signal Parler-TTS uses internally, just done by hand here.
_SCRIPT_VOICE_RANGES = [
    (range(0x0C80, 0x0D00), "kn-IN-SapnaNeural"),   # Kannada
    (range(0x0C00, 0x0C80), "te-IN-ShrutiNeural"),  # Telugu
    (range(0x0900, 0x0980), "hi-IN-SwaraNeural"),   # Devanagari (Hindi)
]
_DEFAULT_EDGE_VOICE = "en-IN-NeerjaNeural"

EDGE_TTS_TIMEOUT = 30  # seconds


def _pick_edge_voice(text: str) -> str:
    for ch in text:
        cp = ord(ch)
        for script_range, voice in _SCRIPT_VOICE_RANGES:
            if cp in script_range:
                return voice
    return _DEFAULT_EDGE_VOICE


async def _edge_tts_synthesize(text: str, voice: str) -> bytes:
    communicate = edge_tts.Communicate(text, voice)
    chunks = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.extend(chunk["data"])
    if not chunks:
        raise RuntimeError("edge-tts returned no audio data")
    return bytes(chunks)


@app.post("/transcribe")
def transcribe(audio: UploadFile):
    # Plain `def`, not `async def`: this body does blocking work (ffmpeg subprocess,
    # GPU inference) with no `await` in it. FastAPI runs sync endpoints in a
    # threadpool automatically, so this doesn't block the event loop the way an
    # `async def` with blocking calls inside it would.
    start = time.monotonic()
    raw = audio.file.read()
    logger.info("transcribe: received %d bytes (filename=%s)", len(raw), audio.filename)
    if not raw:
        raise HTTPException(status_code=400, detail="Empty audio upload.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio file too large.")

    suffix = Path(audio.filename or "audio.webm").suffix or ".webm"
    src_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    wav_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    src_path = src_file.name
    wav_path = wav_file.name

    try:
        src_file.write(raw)
        src_file.close()
        wav_file.close()

        _convert_to_wav(src_path, wav_path)

        try:
            with gpu_lock:
                model = get_asr_model()
                hyps = model.transcribe(wav_path, return_hypotheses=True)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            logger.error("transcribe: CUDA OOM. GPU memory: %s", _gpu_mem_gb())
            raise HTTPException(status_code=503, detail="GPU is out of memory. Please try again.")
    finally:
        if os.path.exists(src_path):
            try:
                os.unlink(src_path)
            except Exception:
                pass
        if os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception:
                pass

    torch.cuda.empty_cache()  # see the note in /speak: keeps reserved memory from ratcheting up
    if not hyps:
        raise HTTPException(status_code=422, detail="Could not transcribe audio.")
    logger.info(
        "transcribe: done in %.2fs, %d chars out. GPU memory: %s",
        time.monotonic() - start, len(hyps[0].text), _gpu_mem_gb(),
    )
    return {"text": hyps[0].text}


@app.post("/speak")
def speak(req: SpeakRequest):
    start = time.monotonic()
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text must not be empty.")

    text = _markdown_to_speech_text(text)
    if not text:
        raise HTTPException(
            status_code=400, detail="No speakable content after removing markdown formatting."
        )
    # Cap applies to the cleaned text — what actually reaches the model —
    # not the raw markdown, which is typically longer than its spoken form.
    if len(text) > MAX_SPEAK_CHARS:
        logger.info("speak: text length %d exceeds %d, truncating for audio synthesis", len(text), MAX_SPEAK_CHARS)
        text = text[:MAX_SPEAK_CHARS].rsplit(" ", 1)[0] + "."
    logger.info("speak: %d chars in", len(text))

    # Primary: edge-tts (cloud, ~3s, better voice quality, free but unofficial).
    # Any failure — network, timeout, API change — falls back to the fully
    # local, self-hosted Parler-TTS path below rather than erroring out.
    voice = _pick_edge_voice(text)
    try:
        audio_bytes = asyncio.run(
            asyncio.wait_for(_edge_tts_synthesize(text, voice), timeout=EDGE_TTS_TIMEOUT)
        )
        logger.info(
            "speak: done via edge-tts (voice=%s) in %.2fs, %d bytes",
            voice, time.monotonic() - start, len(audio_bytes),
        )
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        logger.warning("speak: edge-tts failed (%s), falling back to local Parler-TTS", e)

    # Fallback: local Parler-TTS.
    description_ids = tts_description_tokenizer(req.description, return_tensors="pt").to(DEVICE)
    prompt_ids = tts_tokenizer(text, return_tensors="pt").to(DEVICE)

    try:
        with gpu_lock:
            generation = tts_model.generate(
                input_ids=description_ids.input_ids,
                attention_mask=description_ids.attention_mask,
                prompt_input_ids=prompt_ids.input_ids,
                prompt_attention_mask=prompt_ids.attention_mask,
            )
    except torch.cuda.OutOfMemoryError:
        torch.cuda.empty_cache()
        logger.error("speak: CUDA OOM for %d chars. GPU memory: %s", len(text), _gpu_mem_gb())
        raise HTTPException(status_code=503, detail="GPU is out of memory. Please try again.")

    audio_arr = generation.float().cpu().numpy().squeeze()
    del generation
    # The caching allocator doesn't return freed blocks to the OS on its own —
    # left alone, `reserved` memory only ratchets upward across requests within
    # a process. On an 8GB GPU that's shared with the desktop compositor, that
    # creep can eventually OOM even on modest-length requests. Small perf cost,
    # but keeps headroom stable across a long-running server session.
    torch.cuda.empty_cache()

    buffer = BytesIO()
    sf.write(buffer, audio_arr, tts_model.config.sampling_rate, format="WAV")
    buffer.seek(0)
    logger.info(
        "speak: done via local Parler-TTS in %.2fs, %.1fs of audio. GPU memory after: %s",
        time.monotonic() - start, len(audio_arr) / tts_model.config.sampling_rate, _gpu_mem_gb(),
    )
    return StreamingResponse(buffer, media_type="audio/wav")
