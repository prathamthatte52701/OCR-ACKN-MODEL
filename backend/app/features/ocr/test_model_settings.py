"""The two PaddleOCR model names are settings (OCR_DET_MODEL / OCR_REC_MODEL).

The default is PP-OCRv6 small.

Going back to v4 later must be a config change, not a code change.
"""

import sys
import types
from collections.abc import Iterator
from typing import Any

import pytest
from pydantic import ValidationError

from app.core.config import DEFAULT_OCR_DET_MODEL, DEFAULT_OCR_REC_MODEL, Settings
from app.features.ocr import paddle_runner
from app.features.ocr.paddle_runner import OcrEngineError

V4_DET, V4_REC = "PP-OCRv4_mobile_det", "en_PP-OCRv4_mobile_rec"


def _settings(**extra: Any) -> Settings:
    return Settings(_env_file=None, MONGO_URI="mongodb://x", JWT_SECRET="j" * 40, **extra)  # type: ignore[call-arg]


def test_defaults_are_v6_small() -> None:
    assert DEFAULT_OCR_DET_MODEL == "PP-OCRv6_small_det"
    assert DEFAULT_OCR_REC_MODEL == "PP-OCRv6_small_rec"
    s = _settings()
    assert (s.ocr_det_model, s.ocr_rec_model) == (DEFAULT_OCR_DET_MODEL, DEFAULT_OCR_REC_MODEL)


def test_values_come_from_the_environment_names() -> None:
    s = _settings(OCR_DET_MODEL=V4_DET, OCR_REC_MODEL=V4_REC)
    assert (s.ocr_det_model, s.ocr_rec_model) == (V4_DET, V4_REC)


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_means_the_default(blank: str) -> None:
    s = _settings(OCR_DET_MODEL=blank, OCR_REC_MODEL=blank)
    assert (s.ocr_det_model, s.ocr_rec_model) == (DEFAULT_OCR_DET_MODEL, DEFAULT_OCR_REC_MODEL)


@pytest.mark.parametrize("bad", ["two words", "x" * 101, "tab\there"])
def test_bad_model_names_are_refused_with_a_clear_message(bad: str) -> None:
    with pytest.raises(ValidationError, match="OCR_DET_MODEL"):
        _settings(OCR_DET_MODEL=bad)
    with pytest.raises(ValidationError, match="OCR_REC_MODEL"):
        _settings(OCR_REC_MODEL=bad)


class _Recorder:
    """Stands in for paddleocr.PaddleOCR: remembers how it was built."""

    calls: list[dict[str, Any]] = []
    fail_with: Exception | None = None

    def __init__(self, **kwargs: Any) -> None:
        type(self).calls.append(kwargs)
        failure = type(self).fail_with
        if failure is not None:
            raise failure

    def predict(self, *_a: Any, **_k: Any) -> list[Any]:
        return []


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_Recorder]]:
    _Recorder.calls = []
    _Recorder.fail_with = None
    fake = types.ModuleType("paddleocr")
    fake.PaddleOCR = _Recorder  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "paddleocr", fake)
    paddle_runner._reset_engine_for_tests()
    yield _Recorder
    paddle_runner._reset_engine_for_tests()


def test_engine_is_built_with_the_configured_names_and_every_other_setting_kept(
    recorder: type[_Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paddle_runner.settings, "ocr_det_model", "SOME_det", raising=False)
    monkeypatch.setattr(paddle_runner.settings, "ocr_rec_model", "SOME_rec", raising=False)
    paddle_runner._load_ocr()
    (kwargs,) = recorder.calls
    assert kwargs["text_detection_model_name"] == "SOME_det"
    assert kwargs["text_recognition_model_name"] == "SOME_rec"
    # everything else stays exactly as tuned
    assert kwargs["enable_mkldnn"] is False
    assert kwargs["text_det_limit_side_len"] == 960
    assert kwargs["text_det_limit_type"] == "max"
    assert kwargs["use_doc_orientation_classify"] is True
    assert kwargs["use_doc_unwarping"] is False
    assert kwargs["use_textline_orientation"] is False


def test_default_run_uses_v6_small(recorder: type[_Recorder]) -> None:
    paddle_runner._load_ocr()
    (kwargs,) = recorder.calls
    assert kwargs["text_detection_model_name"] == DEFAULT_OCR_DET_MODEL
    assert kwargs["text_recognition_model_name"] == DEFAULT_OCR_REC_MODEL


def test_unknown_model_name_is_one_clear_error_and_not_a_reload_loop(
    recorder: type[_Recorder], monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    recorder.fail_with = ValueError("Model name 'NOPE_det' is not supported")
    now = [1000.0]
    monkeypatch.setattr(paddle_runner, "_monotonic", lambda: now[0])
    img = tmp_path / "x.png"
    img.write_bytes(b"not used")
    with pytest.raises(OcrEngineError) as first:
        paddle_runner.run_ocr(str(img))
    assert first.value.cls_name == "ValueError" and "NOPE_det" in first.value.short
    assert len(recorder.calls) == 1
    # inside the cooldown the engine is NOT built again for every document: it fails fast
    now[0] += paddle_runner.MODEL_LOAD_RETRY_COOLDOWN_SECONDS - 1
    with pytest.raises(OcrEngineError):
        paddle_runner.run_ocr(str(img))
    assert len(recorder.calls) == 1
    # after the cooldown it is tried again, so a repaired setting recovers by itself
    now[0] += 2
    recorder.fail_with = None
    paddle_runner.run_ocr(str(img))
    assert len(recorder.calls) == 2


def test_rollback_to_v4_is_only_settings(
    recorder: type[_Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(paddle_runner.settings, "ocr_det_model", V4_DET, raising=False)
    monkeypatch.setattr(paddle_runner.settings, "ocr_rec_model", V4_REC, raising=False)
    paddle_runner._load_ocr()
    (kwargs,) = recorder.calls
    assert (kwargs["text_detection_model_name"], kwargs["text_recognition_model_name"]) == (
        V4_DET,
        V4_REC,
    )
