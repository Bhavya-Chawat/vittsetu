import os
import torch
from dotenv import load_dotenv
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer
import soundfile as sf
from pathlib import Path

load_dotenv()
token = os.environ["HF_TOKEN"]
device = "cuda:0" if torch.cuda.is_available() else "cpu"

model = ParlerTTSForConditionalGeneration.from_pretrained(
    "ai4bharat/indic-parler-tts", token=token
).to(device)
tokenizer = AutoTokenizer.from_pretrained("ai4bharat/indic-parler-tts", token=token)
description_tokenizer = AutoTokenizer.from_pretrained(
    model.config.text_encoder._name_or_path, token=token
)

samples = [
    ("hi", "आपको तीन लाख रुपये तक का ऋण मिल सकता है।", "A female speaker delivers a clear, moderate-speed speech with a close recording and no background noise."),
    ("en", "You can get a loan of up to three lakh rupees.", "A female speaker delivers a clear, moderate-speed speech with a close recording and no background noise."),
]

out_dir = Path(__file__).parent / "test_samples"
out_dir.mkdir(exist_ok=True)

for lang, prompt, description in samples:
    description_input_ids = description_tokenizer(description, return_tensors="pt").to(device)
    prompt_input_ids = tokenizer(prompt, return_tensors="pt").to(device)
    generation = model.generate(
        input_ids=description_input_ids.input_ids,
        attention_mask=description_input_ids.attention_mask,
        prompt_input_ids=prompt_input_ids.input_ids,
        prompt_attention_mask=prompt_input_ids.attention_mask,
    )
    audio_arr = generation.cpu().numpy().squeeze()
    out_path = out_dir / f"tts_{lang}.wav"
    sf.write(str(out_path), audio_arr, model.config.sampling_rate)
    print(f"[{lang}] wrote {out_path} ({len(audio_arr)/model.config.sampling_rate:.2f}s)")
