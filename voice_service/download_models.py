"""Run once after cloning to download and cache both voice models.

Usage:
    python voice_service/download_models.py

Requires HF_TOKEN in .env (repo root). Your Hugging Face account must have
been granted access to ARTPARK-IISc/SraVaani-1.0 (manual approval) and
ai4bharat/indic-parler-tts (auto-approved) — see voice_service/README.md.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

token = os.environ.get("HF_TOKEN")
if not token:
    print("ERROR: HF_TOKEN not set. Add it to .env in the repo root.")
    sys.exit(1)


def warm_sravaani():
    print("Downloading SraVaani-1.0 (ASR, ~900MB)...")
    from transformers import AutoModel

    try:
        AutoModel.from_pretrained(
            "ARTPARK-IISc/SraVaani-1.0", trust_remote_code=True, token=token
        )
    except Exception as e:
        if "gated" in str(e).lower() or "403" in str(e):
            print(
                "ERROR: access not yet granted for ARTPARK-IISc/SraVaani-1.0.\n"
                "Request access at https://huggingface.co/ARTPARK-IISc/SraVaani-1.0 "
                "and wait for approval, then re-run this script."
            )
            sys.exit(1)
        raise
    print("SraVaani-1.0 cached.")


def warm_indic_parler_tts():
    print("Downloading Indic Parler-TTS (~2-3GB)...")
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    try:
        model = ParlerTTSForConditionalGeneration.from_pretrained(
            "ai4bharat/indic-parler-tts", token=token
        )
        AutoTokenizer.from_pretrained("ai4bharat/indic-parler-tts", token=token)
        AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path, token=token)
    except Exception as e:
        if "gated" in str(e).lower() or "401" in str(e):
            print(
                "ERROR: access not yet granted for ai4bharat/indic-parler-tts.\n"
                "Visit https://huggingface.co/ai4bharat/indic-parler-tts, accept the "
                "terms (auto-approved), then re-run this script."
            )
            sys.exit(1)
        raise
    print("Indic Parler-TTS cached.")


if __name__ == "__main__":
    import torch

    print(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}")
    warm_sravaani()
    warm_indic_parler_tts()
    print("\nAll models cached. Voice service is ready to run.")
