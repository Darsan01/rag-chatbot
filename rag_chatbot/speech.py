import base64
import binascii
import io
from pathlib import Path
from threading import Lock, Thread
from typing import Any

import numpy as np
import av
import soundfile as sf
import torch
from transformers import pipeline


class LocalSpeechRecognizer:
    def __init__(self, model_size: str = "base") -> None:
        self._model_name = "openai/whisper-tiny" if model_size == "base" else model_size
        self._pipeline = None
        self._pipeline_lock = Lock()
        self._transcription_lock = Lock()

    def _get_pipeline(self):
        if self._pipeline is None:
            with self._pipeline_lock:
                if self._pipeline is None:
                    use_cuda = torch.cuda.is_available()
                    self._pipeline = pipeline(
                        "automatic-speech-recognition",
                        model=self._model_name,
                        device=0 if use_cuda else -1,
                        torch_dtype=torch.float16 if use_cuda else torch.float32,
                    )
        return self._pipeline

    def warm_up(self) -> None:
        self._get_pipeline()

    def warm_up_async(self) -> None:
        Thread(target=self.warm_up, daemon=True, name="whisper-warmup").start()

    @staticmethod
    def _read_audio_file(path: Path) -> tuple[int, np.ndarray]:
        try:
            audio, sampling_rate = sf.read(str(path), dtype="float32")
            return int(sampling_rate), np.asarray(audio, dtype="float32")
        except (RuntimeError, ValueError):
            try:
                with av.open(str(path)) as container:
                    stream = next(
                        stream for stream in container.streams if stream.type == "audio"
                    )
                    frames = [
                        frame.to_ndarray(format="flt")
                        for frame in container.decode(stream)
                    ]
                    if not frames:
                        raise ValueError("The recording contains no audio frames.")
                    audio = np.concatenate(frames, axis=1)
                    if audio.shape[0] > 1:
                        audio = audio.mean(axis=0)
                    return int(stream.rate or 16000), audio.astype("float32")
            except (av.error.Error, StopIteration, ValueError) as error:
                raise ValueError(
                    f"Recorded audio could not be decoded: {error}"
                ) from error

    @staticmethod
    def _read_audio_data(audio_data: str) -> tuple[int, np.ndarray]:
        try:
            encoded = audio_data.split(",", 1)[-1]
            raw_audio = base64.b64decode(encoded, validate=True)
            audio, sampling_rate = sf.read(io.BytesIO(raw_audio), dtype="float32")
            return int(sampling_rate), np.asarray(audio, dtype="float32")
        except (ValueError, RuntimeError, binascii.Error) as error:
            raise ValueError(f"Recorded audio payload could not be decoded: {error}") from error

    def transcribe(self, audio_input: Any) -> str:
        if audio_input is None:
            return ""
        if not self._transcription_lock.acquire(blocking=False):
            raise RuntimeError("A voice recording is already being processed.")
        try:
            if (
                isinstance(audio_input, tuple)
                and len(audio_input) == 2
                and isinstance(audio_input[0], (int, float))
            ):
                sampling_rate, audio = audio_input
                audio = np.asarray(audio, dtype="float32")
            elif isinstance(audio_input, str) and audio_input.startswith("data:"):
                sampling_rate, audio = self._read_audio_data(audio_input)
            else:
                path = Path(str(audio_input))
                if not path.is_file():
                    raise FileNotFoundError(f"Recorded audio file was not found: {path}")
                sampling_rate, audio = self._read_audio_file(path)
            if audio.size == 0:
                raise ValueError("The microphone returned no audio samples.")
            if audio.ndim > 1:
                audio = audio.mean(axis=-1)
            if sampling_rate != 16000:
                target_length = max(1, round(audio.size * 16000 / sampling_rate))
                source_positions = np.linspace(0, audio.size - 1, num=audio.size)
                target_positions = np.linspace(0, audio.size - 1, num=target_length)
                audio = np.interp(target_positions, source_positions, audio).astype(
                    "float32"
                )
                sampling_rate = 16000
            result = self._get_pipeline()(
                {"raw": audio, "sampling_rate": sampling_rate},
                chunk_length_s=30,
                batch_size=1,
            )
            return str(result.get("text", "")).strip()
        finally:
            self._transcription_lock.release()
