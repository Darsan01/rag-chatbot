import os
import torch
import requests
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding
from transformers import AutoModel, AutoTokenizer
from ...setting import RAGSettings
from dotenv import load_dotenv


load_dotenv()


class LocalEmbedding:
    @staticmethod
    def set(setting: RAGSettings | None = None, **kwargs):
        setting = setting or RAGSettings()
        model_name = setting.ingestion.embed_llm
        if model_name != "text-embedding-ada-002":
            device = "cuda" if torch.cuda.is_available() else "cpu"
            dtype = torch.float16 if device == "cuda" else torch.float32
            model = AutoModel.from_pretrained(
                model_name,
                torch_dtype=dtype,
                trust_remote_code=True,
            ).to(device)
            return HuggingFaceEmbedding(
                model=model,
                tokenizer=AutoTokenizer.from_pretrained(
                    model_name, torch_dtype=dtype
                ),
                cache_folder=os.path.join(os.getcwd(), setting.ingestion.cache_folder),
                trust_remote_code=True,
                embed_batch_size=setting.ingestion.embed_batch_size,
                device=device,
            )
        else:
            return OpenAIEmbedding()

    @staticmethod
    def pull(host: str, **kwargs):
        setting = RAGSettings()
        payload = {"name": setting.ingestion.embed_llm}
        return requests.post(f"http://{host}:11434/api/pull", json=payload, stream=True)

    @staticmethod
    def check_model_exist(host: str, **kwargs) -> bool:
        setting = RAGSettings()
        data = requests.get(f"http://{host}:11434/api/tags").json()
        list_model = [d["name"] for d in data["models"]]
        if setting.ingestion.embed_llm in list_model:
            return True
        return False
