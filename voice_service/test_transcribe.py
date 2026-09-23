from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

from transformers import AutoModel

token = os.environ["HF_TOKEN"]
model = AutoModel.from_pretrained(
    "ARTPARK-IISc/SraVaani-1.0",
    trust_remote_code=True,
    token=token,
)

audio_path = Path(__file__).parent / "test_samples" / "test_en.wav"
hyps = model.transcribe(str(audio_path), return_hypotheses=True)
print(hyps)
