"""Fixed model handling: one OpenAI list, timeouts, clear errors.

What was wrong in the original:
- The OpenAI list was hard-coded in 3 different places and they
  disagreed: model.py knew gpt-4o, ui.py only knew gpt-3.5-turbo
  and gpt-4, so gpt-4o was treated as an Ollama model to pull.
- check_model_exist() / pull() had no timeout and used
  data["models"] directly - Ollama down = crash, not a message.
- No check for OPENAI_API_KEY before trying an OpenAI model.
"""
import os

import requests
from llama_index.llms.ollama import Ollama
from llama_index.llms.openai import OpenAI

from ...setting import RAGSettings

OPENAI_MODELS = {"gpt-3.5-turbo", "gpt-4", "gpt-4o", "gpt-4-turbo"}


class LocalRAGModel:
    @staticmethod
    def set(
        model_name: str = "llama3:8b-instruct-q8_0",
        system_prompt: str | None = None,
        host: str = "host.docker.internal",
        setting: RAGSettings | None = None,
    ):
        setting = setting or RAGSettings()
        if model_name in OPENAI_MODELS:
            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError(
                    "OPENAI_API_KEY is not set. Add it to your .env "
                    "or pick an Ollama model instead."
                )
            return OpenAI(model=model_name, temperature=setting.ollama.temperature)

        return Ollama(
            model=model_name,
            system_prompt=system_prompt,
            base_url=f"http://{host}:{setting.ollama.port}",
            temperature=setting.ollama.temperature,
            context_window=setting.ollama.context_window,
            request_timeout=setting.ollama.request_timeout,
            additional_kwargs={
                "tfs_z": setting.ollama.tfs_z,
                "top_k": setting.ollama.top_k,
                "top_p": setting.ollama.top_p,
                "repeat_last_n": setting.ollama.repeat_last_n,
                "repeat_penalty": setting.ollama.repeat_penalty,
            },
        )

    @staticmethod
    def pull(host: str, model_name: str):
        setting = RAGSettings()
        payload = {"name": model_name}
        return requests.post(
            f"http://{host}:{setting.ollama.port}/api/pull",
            json=payload,
            stream=True,
            timeout=10,
        )

    @staticmethod
    def check_model_exist(host: str, model_name: str) -> bool:
        setting = RAGSettings()
        try:
            data = requests.get(
                f"http://{host}:{setting.ollama.port}/api/tags", timeout=5
            ).json()
        except requests.RequestException:
            return False
        models = data.get("models") or []
        return model_name in [m.get("name") for m in models]
