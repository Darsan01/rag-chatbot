"""Fixed pipeline: lazy loading, no empty-model LLM, no None crashes.

What was wrong in the original:
- __init__ created TWO LLMs and an embedding model up front, one
  with model_name="" (Ollama(model="") - broken). Startup loaded
  a ~1.3 GB embedding model before the user picked anything.
- set_embed_model(model_name, host) passed the name as `setting`
  to LocalEmbedding.set(), so it crashed. See embedding.py.
- query() / clear_conversation() called self._query_engine.reset()
  with no None check - asking a question before picking a model
  crashed instead of showing "pick a model first".
- set_chat_mode() called set_language(self._language) - a no-op.
- Settings.llm / Settings.embed_model were set in 3 places, so it
  was never clear which model was actually answering.
"""
from llama_index.core import Settings
from llama_index.core.chat_engine.types import StreamingAgentChatResponse
from llama_index.core.prompts import ChatMessage, MessageRole

from .core import (
    LocalChatEngine,
    LocalDataIngestion,
    LocalEmbedding,
    LocalRAGModel,
    LocalVectorStore,
    get_system_prompt,
)
from .setting import RAGSettings


class LocalRAGPipeline:
    def __init__(self, host: str = "host.docker.internal") -> None:
        self._host = host
        self._setting = RAGSettings()
        self._language = "eng"
        # Sensible default from settings, never "".
        self._model_name = self._setting.ollama.llm
        self._system_prompt = get_system_prompt("eng", is_rag_prompt=False)
        self._engine = LocalChatEngine(host=host)
        self._ingestion = LocalDataIngestion()
        self._vector_store = LocalVectorStore(host=host)
        # Lazy: no LLM / embedding model is loaded here.
        # They load on first use, in _ensure_llm() / _ensure_embed().
        self._llm = None
        self._embed_loaded = False
        self._query_engine = None

    # -- lazy loading -------------------------------------------------
    def _ensure_llm(self):
        if self._llm is None:
            self._llm = LocalRAGModel.set(
                model_name=self._model_name,
                system_prompt=self._system_prompt,
                host=self._host,
            )
            Settings.llm = self._llm
        return self._llm

    def _ensure_embed(self):
        if not self._embed_loaded:
            Settings.embed_model = LocalEmbedding.set(setting=self._setting)
            self._embed_loaded = True
        return Settings.embed_model

    # -- simple getters / setters -------------------------------------
    def get_model_name(self):
        return self._model_name

    def set_model_name(self, model_name: str):
        if not model_name:
            raise ValueError("Model name must not be empty.")
        self._model_name = model_name
        self._llm = None  # force reload with the new model

    def get_language(self):
        return self._language

    def set_language(self, language: str):
        self._language = language

    def get_system_prompt(self):
        return self._system_prompt

    def set_system_prompt(self, system_prompt: str | None = None):
        self._system_prompt = system_prompt or get_system_prompt(
            language=self._language, is_rag_prompt=self._ingestion.check_nodes_exist()
        )

    def set_model(self):
        self._ensure_llm()

    def reset_engine(self):
        self._query_engine = self._engine.set_engine(
            llm=self._ensure_llm(), nodes=[], language=self._language
        )

    def reset_documents(self):
        self._ingestion.reset()
        self._query_engine = None

    def clear_conversation(self):
        if self._query_engine is not None:
            self._query_engine.reset()

    def reset_conversation(self):
        self.reset_engine()
        self.set_system_prompt(
            get_system_prompt(language=self._language, is_rag_prompt=False)
        )

    def set_embed_model(self, model_name: str):
        # Fixed signature: name is a name, not a `setting` object.
        Settings.embed_model = LocalEmbedding.set(
            model_name=model_name, setting=self._setting
        )
        self._embed_loaded = True

    def pull_model(self, model_name: str):
        return LocalRAGModel.pull(self._host, model_name)

    def pull_embed_model(self, model_name: str):
        return LocalEmbedding.pull(self._host, setting=self._setting)

    def check_exist(self, model_name: str) -> bool:
        return LocalRAGModel.check_model_exist(self._host, model_name)

    def check_exist_embed(self, model_name: str) -> bool:
        return LocalEmbedding.check_model_exist(self._host, setting=self._setting)

    def store_nodes(self, input_files: list[str] | None = None) -> None:
        self._ensure_embed()
        self._ingestion.store_nodes(input_files=input_files)

    def set_chat_mode(self, system_prompt: str | None = None):
        self.set_system_prompt(system_prompt)
        self.set_model()
        self.set_engine()

    def set_engine(self):
        self._query_engine = self._engine.set_engine(
            llm=self._ensure_llm(),
            nodes=self._ingestion.get_ingested_nodes(),
            language=self._language,
        )

    def get_history(self, chatbot: list[list[str]]):
        history = []
        for chat in chatbot:
            if not chat or not chat[0]:
                continue
            history.append(ChatMessage(role=MessageRole.USER, content=chat[0]))
            if len(chat) > 1 and chat[1]:
                history.append(
                    ChatMessage(role=MessageRole.ASSISTANT, content=chat[1])
                )
        return history

    def query(
        self, mode: str, message: str, chatbot: list[list[str]]
    ) -> StreamingAgentChatResponse:
        if not self._model_name:
            raise ValueError("Pick a model first.")
        if self._query_engine is None:
            self.set_engine()
        if mode == "chat":
            history = self.get_history(chatbot)
            return self._query_engine.stream_chat(message, history)
        self._query_engine.reset()
        return self._query_engine.stream_chat(message)
