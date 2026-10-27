"""Fixed embedding: one clear API, no double model load, no crash on Ollama down.

What was wrong in the original:
- set() took `setting` as its first arg, but pipeline.py called
  set(host=host) and set(model_name, host) - the model name was
  passed as `setting`, so setting.ingestion.embed_llm crashed.
- It manually loaded AutoModel + AutoTokenizer, then handed them to
  HuggingFaceEmbedding, which loads the model again. Slow + 2x RAM.
- AutoTokenizer.from_pretrained(..., torch_dtype=...) is not a
  valid tokenizer kwarg.
- check_model_exist() did requests.get() with no timeout and
  data["models"] with no .get() - Ollama down = unhandled crash.
"""
import os

import requests
import torch
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding

from ...setting import RAGSettings


class LocalEmbedding:
    @staticmethod
    def set(
        model_name: str | None = None,
        setting: RAGSettings | None = None,
    ):
        setting = setting or RAGSettings()
        model_name = model_name or setting.ingestion.embed_llm

        if model_name == "text-embedding-ada-002":
            return OpenAIEmbedding()

        # Let HuggingFaceEmbedding load the model once, on the
        # right device. No manual AutoModel / AutoTokenizer.
        device = "cuda" if torch.cuda.is_available() else "cpu"
        return HuggingFaceEmbedding(
            model_name=model_name,
            cache_folder=os.path.join(os.getcwd(), setting.ingestion.cache_folder),
            trust_remote_code=True,
            embed_batch_size=setting.ingestion.embed_batch_size,
            device=device,
        )

    @staticmethod
    def pull(host: str, setting: RAGSettings | None = None):
        setting = setting or RAGSettings()
        payload = {"name": setting.ingestion.embed_llm}
        return requests.post(
            f"http://{host}:{setting.ollama.port}/api/pull",
            json=payload,
            stream=True,
            timeout=10,
        )

    @staticmethod
    def check_model_exist(host: str, setting: RAGSettings | None = None) -> bool:
        setting = setting or RAGSettings()
        try:
            data = requests.get(
                f"http://{host}:{setting.ollama.port}/api/tags", timeout=5
            ).json()
        except requests.RequestException:
            return False
        models = data.get("models") or []
        return setting.ingestion.embed_llm in [m.get("name") for m in models]
