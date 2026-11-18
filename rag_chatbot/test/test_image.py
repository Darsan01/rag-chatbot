import base64
import json
from types import SimpleNamespace

from PIL import Image

from rag_chatbot.image import LocalImageService
from rag_chatbot.setting import RAGSettings


class FakeResponse:
    status_code = 200

    def __init__(self, messages):
        self._messages = messages

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def raise_for_status(self):
        return None

    def iter_lines(self, decode_unicode=False):
        assert decode_unicode
        for message in self._messages:
            yield json.dumps({"message": {"content": message}})


def test_describe_streams_ollama_vision_response(tmp_path, monkeypatch):
    image_path = tmp_path / "input.png"
    image_path.write_bytes(b"image-bytes")
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(["A blue ", "square."])

    monkeypatch.setattr("rag_chatbot.image.requests.post", fake_post)
    service = LocalImageService(host="localhost")

    assert "".join(service.describe(str(image_path), "What is shown?")) == (
        "A blue square."
    )
    message = captured["json"]["messages"][0]
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert message["content"] == "What is shown?"
    assert base64.b64decode(message["images"][0]) == b"image-bytes"


def test_describe_sends_multiple_images(tmp_path, monkeypatch):
    first = tmp_path / "first.png"
    second = tmp_path / "second.jpg"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    captured = {}

    def fake_post(_url, **kwargs):
        captured.update(kwargs)
        return FakeResponse(["Two images."])

    monkeypatch.setattr("rag_chatbot.image.requests.post", fake_post)
    service = LocalImageService(host="localhost")

    assert "".join(service.describe([str(first), str(second)], "Compare them")) == (
        "Two images."
    )
    encoded = captured["json"]["messages"][0]["images"]
    assert [base64.b64decode(item) for item in encoded] == [b"first", b"second"]


def test_generate_saves_pipeline_image(tmp_path, monkeypatch):
    setting = RAGSettings()
    setting.image.output_dir = str(tmp_path)
    service = LocalImageService(host="localhost", setting=setting)

    class FakePipeline:
        def set_progress_bar_config(self, **_kwargs):
            return None

        def to(self, _device):
            return self

        def __call__(self, **kwargs):
            assert kwargs["prompt"] == "A green circle"
            return SimpleNamespace(images=[Image.new("RGB", (8, 8), "green")])

    service._generator = FakePipeline()
    monkeypatch.setattr(service, "_unload_ollama_model", lambda: None)
    monkeypatch.setattr("rag_chatbot.image.torch.cuda.is_available", lambda: False)

    output_path = service.generate("A green circle")

    with Image.open(output_path) as generated:
        assert generated.size == (8, 8)


def test_release_generator_moves_cached_pipeline_to_cpu(monkeypatch):
    service = LocalImageService(host="localhost")
    moved_to = []
    service._generator = SimpleNamespace(to=lambda device: moved_to.append(device))
    service._generator_on_gpu = True
    monkeypatch.setattr("rag_chatbot.image.torch.cuda.empty_cache", lambda: None)

    service.release_generator()

    assert moved_to == ["cpu"]
    assert service._generator_on_gpu is False
