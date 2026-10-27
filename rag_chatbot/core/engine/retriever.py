"""Fixed retriever: one hybrid path, no router tax, no Ellipsis bug.

What was wrong in the original - this is the main reason it felt slow:
- get_retrievers() used RouterRetriever whenever there were >6 nodes
  (i.e. almost always). That built TWO hybrid retrievers, each with
  BM25 + vector, plus an LLMSingleSelector - so one question cost
  1 LLM call to route + 5 generated queries x 2 retrievers + a
  rerank, before the answer LLM even started.
- TwoStageRetriever.__init__ had similarity_top_k: int = ...
  (Ellipsis) and passed it straight to the parent. Broken default.
- _aretrieve() called the sync SentenceTransformerRerank inside
  an async method, blocking the event loop.
- Every set_engine() call rebuilt VectorStoreIndex(nodes) from
  scratch, and re-created the reranker (BAAI/bge-reranker-large).
  Changing language / model / prompt = full rebuild.

Fix: one retriever, chosen by size. Small docs = vector only.
Larger docs = ONE hybrid (BM25 + vector, 2 generated queries,
not 5), reranker created once and reused.
"""
from typing import List

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.postprocessor import SentenceTransformerRerank
from llama_index.core.retrievers import (
    BaseRetriever,
    QueryFusionRetriever,
    VectorIndexRetriever,
)
from llama_index.core.schema import BaseNode
from llama_index.core.llms.llm import LLM
from llama_index.retrievers.bm25 import BM25Retriever

from ..prompt import get_query_gen_prompt
from ...setting import RAGSettings


class LocalRetriever:
    def __init__(self, setting: RAGSettings | None = None, host: str = "host.docker.internal"):
        self._setting = setting or RAGSettings()
        self._host = host
        self._reranker: SentenceTransformerRerank | None = None

    def _get_reranker(self):
        # Load the large reranker once, not on every query / rebuild.
        if self._reranker is None:
            self._reranker = SentenceTransformerRerank(
                top_n=self._setting.retriever.top_k_rerank,
                model=self._setting.retriever.rerank_llm,
            )
        return self._reranker

    def _get_normal_retriever(self, vector_index, llm=None, language="eng"):
        return VectorIndexRetriever(
            index=vector_index,
            similarity_top_k=self._setting.retriever.similarity_top_k,
            embed_model=Settings.embed_model,
        )

    def _get_hybrid_retriever(self, vector_index, llm=None, language="eng"):
        vector_retriever = VectorIndexRetriever(
            index=vector_index,
            similarity_top_k=self._setting.retriever.similarity_top_k,
            embed_model=Settings.embed_model,
        )
        bm25_retriever = BM25Retriever.from_defaults(
            index=vector_index,
            similarity_top_k=self._setting.retriever.similarity_top_k,
        )
        # num_queries=2, not 5: 5 generated queries x 2 retrievers
        # was most of the latency, for very little extra recall.
        return QueryFusionRetriever(
            retrievers=[bm25_retriever, vector_retriever],
            retriever_weights=self._setting.retriever.retriever_weights,
            llm=llm,
            query_gen_prompt=get_query_gen_prompt(language),
            similarity_top_k=self._setting.retriever.top_k_rerank,
            num_queries=2,
            mode=self._setting.retriever.fusion_mode,
        )

    def get_retrievers(
        self,
        nodes: List[BaseNode],
        llm: LLM | None = None,
        language: str = "eng",
    ) -> BaseRetriever:
        # Build the index once per set_engine() call - and note in
        # REVIEW.md: the real fix is to persist this index in
        # Chroma (settings already define data/chroma) instead of
        # rebuilding it on every model / language / prompt change.
        vector_index = VectorStoreIndex(nodes=nodes)

        if len(nodes) <= self._setting.retriever.top_k_rerank:
            return self._get_normal_retriever(vector_index, llm, language)

        return self._get_hybrid_retriever(vector_index, llm, language)
