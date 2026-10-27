"""Fixed ingestion: keeps Unicode, keeps page numbers, no stale cache.

What was wrong in the original:
- _filter_text() used a Latin-only regex, so Nepali text became "" and
  paragraph breaks / dashes were stripped. Answers lost context.
- All pages were concatenated into ONE Document, so chunking crossed
  page boundaries and no chunk knew which page it came from.
- fitz.open() was never closed (file-handle leak).
- Cache key was just the file name: two different PDFs called
  "report.pdf" returned the first one's nodes.
- store_nodes() reset _ingested_file every call, so uploading a
  second batch silently dropped the first batch from the chat.
- Settings.embed_model(nodes, ...) is not a valid llama-index API.
  Embedding is left to VectorStoreIndex, which does it correctly.
"""
import hashlib
import re

import fitz
from llama_index.core import Document
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import BaseNode
from typing import List

from ...setting import RAGSettings


class LocalDataIngestion:
    def __init__(self, setting: RAGSettings | None = None) -> None:
        self._setting = setting or RAGSettings()
        self._node_store: dict[str, list[BaseNode]] = {}
        self._ingested_file: list[str] = []  # cache keys, in upload order

    @staticmethod
    def _clean_text(text: str) -> str:
        # Keep ALL Unicode (Nepali, Vietnamese, accents...). Only
        # normalise whitespace: collapse spaces/tabs, keep paragraph breaks.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _cache_key(path: str) -> str:
        # Same name + different content = different key.
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()[:16]
        name = path.strip().split("/")[-1]
        return f"{name}:{digest}"

    def store_nodes(self, input_files: list[str] | None = None) -> List[BaseNode]:
        input_files = input_files or []
        if not input_files:
            return []

        splitter = SentenceSplitter.from_defaults(
            chunk_size=self._setting.ingestion.chunk_size,
            chunk_overlap=self._setting.ingestion.chunk_overlap,
            paragraph_separator=self._setting.ingestion.paragraph_sep,
            secondary_chunking_regex=self._setting.ingestion.chunking_regex,
        )

        return_nodes: List[BaseNode] = []
        for input_file in input_files:
            key = self._cache_key(input_file)
            if key in self._node_store:
                return_nodes.extend(self._node_store[key])
                if key not in self._ingested_file:
                    self._ingested_file.append(key)
                continue

            file_name = input_file.strip().split("/")[-1]
            documents: list[Document] = []

            if file_name.lower().endswith(".pdf"):
                # One Document per page, with page metadata. `with`
                # closes the file - the original never closed it.
                with fitz.open(input_file) as pdf:
                    for page_no, page in enumerate(pdf, start=1):
                        text = self._clean_text(page.get_text("text"))
                        if not text:
                            continue
                        documents.append(
                            Document(
                                text=text,
                                metadata={
                                    "file_name": file_name,
                                    "page": page_no,
                                    "total_pages": len(pdf),
                                },
                            )
                        )
            elif file_name.lower().endswith((".txt", ".csv", ".md")):
                with open(input_file, encoding="utf-8", errors="ignore") as f:
                    text = self._clean_text(f.read())
                if text:
                    documents.append(
                        Document(text=text, metadata={"file_name": file_name})
                    )
            else:
                raise ValueError(f"Unsupported file type: {file_name}")

            nodes = splitter(documents, show_progress=True)
            self._node_store[key] = nodes
            self._ingested_file.append(key)
            return_nodes.extend(nodes)

        return return_nodes

    def reset(self):
        self._node_store = {}
        self._ingested_file = []

    def check_nodes_exist(self):
        return bool(self._node_store)

    def get_all_nodes(self):
        return_nodes = []
        for nodes in self._node_store.values():
            return_nodes.extend(nodes)
        return return_nodes

    def get_ingested_nodes(self):
        # _ingested_file is now cumulative, not reset per upload,
        # so a second upload no longer drops the first batch.
        return_nodes = []
        for key in self._ingested_file:
            return_nodes.extend(self._node_store[key])
        return return_nodes
