import base64
import gc
import json
import uuid
from pathlib import Path
from threading import Lock
from typing import Iterator

import requests
import torch

from .setting import RAGSettings


class LocalImageService:
    def __init__(
        self,
        host: str = "host.docker.internal",
        setting: RAGSettings | None = None,
    ) -> None:
        self._host = host
        self._setting = setting or RAGSettings()
        self._generator = None
        self._generator_on_gpu = False
        self._generation_lock = Lock()
        self._output_dir = Path(self._setting.image.output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _ollama_url(self) -> str:
        return f"http://{self._host}:{self._setting.ollama.port}"

    def describe(self, image_path: str | list[str], prompt: str) -> Iterator[str]:
        self.release_generator()
        paths = (
            [Path(image_path)]
            if isinstance(image_path, str)
            else list(map(Path, image_path))
        )
        for path in paths:
            if not path.is_file():
                raise FileNotFoundError(f"Image file was not found: {path}")

        encoded = [
            base64.b64encode(path.read_bytes()).decode("ascii") for path in paths
        ]
        payload = {
            "model": self._setting.image.vision_model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt.strip() or "Describe this image in detail.",
                    "images": encoded,
                }
            ],
            "stream": True,
            "keep_alive": self._setting.ollama.keep_alive,
        }
        with requests.post(
            f"{self._ollama_url}/api/chat",
            json=payload,
            stream=True,
            timeout=self._setting.ollama.request_timeout,
        ) as response:
            if response.status_code == 404:
                raise RuntimeError(
                    f"Vision model '{self._setting.image.vision_model}' is not installed. "
                    f"Run: ollama pull {self._setting.image.vision_model}"
                )
            response.raise_for_status()
            for data in response.iter_lines(decode_unicode=True):
                if not data:
                    continue
                item = json.loads(data)
                content = item.get("message", {}).get("content", "")
                if content:
                    yield content

    def _unload_ollama_model(self) -> None:
        try:
            requests.post(
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._setting.ollama.llm,
                    "prompt": "",
                    "keep_alive": 0,
                    "stream": False,
                },
                timeout=30,
            )
        except requests.RequestException:
            pass

    def _load_generator(self):
        if self._generator is not None:
            return self._generator
        try:
            from diffusers import AutoPipelineForText2Image
        except ImportError as error:
            raise RuntimeError(
                "Image generation dependencies are missing. Run: uv sync"
            ) from error

        dtype = torch.float16 if torch.cuda.is_available() else torch.float32
        self._generator = AutoPipelineForText2Image.from_pretrained(
            self._setting.image.generation_model,
            torch_dtype=dtype,
            cache_dir=self._setting.ingestion.cache_folder,
        )
        self._generator.set_progress_bar_config(disable=True)
        return self._generator

    def generate(self, prompt: str) -> str:
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("Enter a prompt before generating an image.")
        if not self._generation_lock.acquire(blocking=False):
            raise RuntimeError("An image is already being generated.")

        try:
            self._unload_ollama_model()
            pipeline = self._load_generator()
            device = "cuda" if torch.cuda.is_available() else "cpu"
            if device == "cuda" and not self._generator_on_gpu:
                pipeline.to(device)
                self._generator_on_gpu = True
            elif device == "cpu":
                pipeline.to(device)
            generator = torch.Generator(device=device).manual_seed(torch.seed())
            image = pipeline(
                prompt=prompt,
                num_inference_steps=self._setting.image.inference_steps,
                guidance_scale=self._setting.image.guidance_scale,
                height=self._setting.image.height,
                width=self._setting.image.width,
                generator=generator,
            ).images[0]
            output_path = self._output_dir / f"generated-{uuid.uuid4().hex}.png"
            image.save(output_path)
            return str(output_path.resolve())
        finally:
            gc.collect()
            self._generation_lock.release()

    def release_generator(self) -> None:
        if self._generator is not None and self._generator_on_gpu:
            self._generator.to("cpu")
            self._generator_on_gpu = False
            torch.cuda.empty_cache()
            gc.collect()
