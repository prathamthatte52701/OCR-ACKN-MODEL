"""Runs PaddleOCR against a header-crop image.

Was previously spawning a fresh child process - and re-instantiating
PaddleOCR (full model load from disk) - on every single call. Model init for
these det+rec models routinely takes 30-90s+, so every document paid that
cost on top of actual inference, which is what made processing look like
minutes-per-document instead of the expected 5-15s. Fixed: the PaddleOCR
instance is now a lazy singleton, created once (first call) and reused for
the lifetime of the worker process. Concurrent access is already serialized
by pipeline.py's _ocr_lock, but _init_lock below guards singleton creation
in isolation too (defense in depth, not load-bearing under current callers).

Trade-off from dropping the per-call child process: a genuine crash inside
PaddleOCR itself is no longer contained to a disposable subprocess - it would
now take down the worker thread it's running in. The try/except below keeps
that from propagating as an unhandled exception (falls back to None, same
contract as before), but a true native-level crash (segfault) in the C++
inference backend is not catchable from Python either way and was never
actually caught by the old subprocess+join code path for a *hang* (only
process.join's timeout dealt with hangs; a hard crash would have shown up as
an empty result_queue, handled the same way here).
"""

import os
import re
import tempfile
import threading
import time
from typing import Any

from loguru import logger

from app.features.ocr.row_assembly import assemble_rows

# Confirmed root cause of "all GET APIs are slow" (measured, not assumed):
# OpenBLAS/OMP default to using every logical core for PaddleOCR's internal
# matrix math, unless told otherwise - on this 12-core machine that means an
# in-flight OCR call saturates all 12 cores, starving the event-loop thread
# of CPU time even though OCR itself runs off-loop via asyncio.to_thread.
# Measured before this fix: GET /documents went from ~350ms idle to 8.8s
# while one OCR job was running. Must be set before paddle/numpy import -
# these libraries read the env var once at native-library load time.
_CPU_THREAD_CAP = "6"
os.environ.setdefault("OMP_NUM_THREADS", _CPU_THREAD_CAP)
os.environ.setdefault("OPENBLAS_NUM_THREADS", _CPU_THREAD_CAP)
os.environ.setdefault("MKL_NUM_THREADS", _CPU_THREAD_CAP)
# PaddleX's own inference-thread-count knob (see pp_option.py) - defaults to
# 10 if unset, same problem from a different config surface.
os.environ.setdefault("PADDLE_PDX_CPU_NUM_THREADS", _CPU_THREAD_CAP)

OCR_TIMEOUT_SECONDS_PDF = 180
# Deliberately higher than the PDF path - buffer against slower image
# processing while other timing fixes land, per explicit instruction.
OCR_TIMEOUT_SECONDS_IMAGE = 500

_ocr_instance: Any = None
_init_lock = threading.Lock()

# A model that failed to load is remembered for this long, so a broken engine fails fast instead of
# being reloaded for every single document; after it the load is tried again, so a repaired engine
# recovers by itself (a failure is never permanent).
MODEL_LOAD_RETRY_COOLDOWN_SECONDS = 60.0
_monotonic = time.monotonic  # patchable clock
_load_failure: tuple[float, str, str] | None = None  # (when, exception class, short message)


def _reset_engine_for_tests() -> None:
    global _ocr_instance, _load_failure
    _ocr_instance = None
    _load_failure = None


MAX_ERROR_MESSAGE_CHARS = 200
# The profile folder name can contain spaces ("John Smith"), so match up to the next separator.
_USER_PATH_RE = re.compile(
    r"[A-Za-z]:[\\/]+(?:Users|Documents and Settings)[\\/]+[^\\/'\"]+", re.IGNORECASE
)
_HOME_PATH_RE = re.compile(r"/(?:home|Users)/[^/'\"]+")


def short_error_message(exc: BaseException) -> str:
    """A short, safe-to-log version of an exception message: no user name from a temp/home path,
    one line, at most MAX_ERROR_MESSAGE_CHARS characters. Never contains OCR text (engine errors
    do not carry it)."""
    text = str(exc)
    text = text.replace(tempfile.gettempdir(), "<tmp>")
    text = _USER_PATH_RE.sub("<user>", text)
    text = _HOME_PATH_RE.sub("<user>", text)
    return " ".join(text.split())[:MAX_ERROR_MESSAGE_CHARS]


def _is_file_error(exc: BaseException) -> bool:
    """True only for the engine's own 'could not read this file' failure. The pipeline already
    decodes the image with OpenCV before the engine call, so a cv2 or Pillow error raised INSIDE
    the engine is the engine's problem, not the file's. (Probed against the real engine: a
    truncated or non-image file raises a plain Exception('Image read Error: ...'); blank and tiny
    but valid images simply return an empty result.)"""
    return type(exc) is Exception and str(exc).startswith("Image read Error")


class OcrEngineError(Exception):
    """The OCR engine failed on a call (model load, predictor, memory...). cls_name is the original
    exception class, short a sanitized message (at most 200 characters), file_caused is True when
    the failure is clearly the image file's fault (then the document is 'no text', not an engine
    failure)."""

    def __init__(self, cls_name: str, short: str, file_caused: bool = False) -> None:
        super().__init__(f"{cls_name}: {short}")
        self.cls_name = cls_name
        self.short = short
        self.file_caused = file_caused

    @classmethod
    def from_exception(cls, exc: BaseException) -> "OcrEngineError":
        return cls(type(exc).__name__, short_error_message(exc), _is_file_error(exc))


def _get_ocr() -> Any:
    """The engine, or an OcrEngineError. A failed load is cached for the cooldown."""
    global _load_failure
    if _ocr_instance is not None:
        return _ocr_instance
    failure = _load_failure
    if failure is not None and _monotonic() - failure[0] < MODEL_LOAD_RETRY_COOLDOWN_SECONDS:
        raise OcrEngineError(failure[1], failure[2])
    try:
        engine = _load_ocr()
    except Exception as exc:  # noqa: BLE001
        _load_failure = (_monotonic(), type(exc).__name__, short_error_message(exc))
        raise
    _load_failure = None
    return engine


def _load_ocr() -> Any:
    global _ocr_instance
    if _ocr_instance is None:
        with _init_lock:
            if _ocr_instance is None:
                from paddleocr import PaddleOCR

                _ocr_instance = PaddleOCR(
                    # Mobile/lite models instead of the PP-OCRv6 "server"
                    # models this defaulted to - the server models are
                    # meaningfully heavier on RAM/CPU, which is the suspected
                    # driver behind repeated crashes on this CPU-only
                    # i5-12th-gen machine. Accuracy tradeoff is acceptable
                    # here since the app already has the character-confusion
                    # auto-correction and G/P-prefix validation safety nets
                    # layered on top of raw OCR output (see
                    # ocr/extraction.py) - those exist precisely to catch
                    # exactly the kind of noisier reads a lighter model
                    # produces.
                    text_detection_model_name="PP-OCRv4_mobile_det",
                    text_recognition_model_name="en_PP-OCRv4_mobile_rec",
                    # True at init so the (tiny, PP-LCNet_x1_0_doc_ori)
                    # classifier model is loaded once and available - but
                    # run_ocr always explicitly passes
                    # use_doc_orientation_classify=False per call unless
                    # preprocessing.py's quality gate flagged likely
                    # misorientation, so it never actually runs (and costs no
                    # extra time) on the default path. Measured: ~10ms
                    # overhead on a header crop when it IS invoked - cheap
                    # enough that gating it per-call rather than globally is
                    # about correctness (don't fix orientation on an
                    # already-upright scan), not about raw cost.
                    use_doc_orientation_classify=True,
                    use_doc_unwarping=False,
                    use_textline_orientation=False,
                    # This paddlepaddle CPU build's oneDNN backend throws
                    # NotImplementedError (ConvertPirAttribute2RuntimeAttribute)
                    # on this model's ops - disabling mkldnn avoids that path.
                    enable_mkldnn=False,
                    # The header crop is rendered at a Tesseract-tuned scale
                    # (~3188px wide) and fed to the detector at full
                    # resolution with no cap - capping the detection-stage
                    # side length is the standard PaddleOCR lever for this
                    # exact situation. Recognition still runs on crops from
                    # the original full-resolution image, so text quality is
                    # unaffected; measured ~24% faster with identical
                    # extracted values for the fields that matter.
                    text_det_limit_side_len=960,
                    text_det_limit_type="max",
                )
    return _ocr_instance


def run_ocr(
    image_path: str,
    *,
    use_doc_orientation_classify: bool = False,
    text_det_limit_side_len: int | None = None,
) -> str | None:
    """Blocking call - invoke via asyncio.to_thread from async code. Reuses
    the cached PaddleOCR singleton instead of loading the model fresh.

    use_doc_orientation_classify/text_det_limit_side_len are per-call
    overrides threaded from preprocessing.py's quality gate (Feature 6) -
    defaults reproduce the original fast path exactly (classifier off,
    detector limit falls back to the singleton's init-time 960).

    Returns the assembled text, row-grouped (see row_assembly.assemble_rows)
    rather than one raw text box per line, or None ONLY for a genuinely empty
    result. Any engine failure (model load, predictor, memory...) raises
    OcrEngineError so the caller can tell "engine broken" from "no text"."""
    try:
        ocr = _get_ocr()
        results = ocr.predict(
            image_path,
            use_doc_orientation_classify=use_doc_orientation_classify,
            text_det_limit_side_len=text_det_limit_side_len,
        )
        row_lines: list[str] = []
        for r in results:
            res = r.json.get("res", {})
            texts = res.get("rec_texts", [])
            boxes = res.get("rec_boxes", [])
            row_lines.extend(assemble_rows(texts, boxes))
        text = "\n".join(row_lines) or None
        return text
    except OcrEngineError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OcrEngineError.from_exception(exc) from exc


_orientation_model: Any = None
_orientation_init_lock = threading.Lock()
_ORIENTATION_LOG_EVERY_SECONDS = 60.0
_last_orientation_log = 0.0


def classify_page_orientation(png_bytes: bytes) -> tuple[int, float]:
    """Blocking - call via asyncio.to_thread, under pipeline.py's OCR lock
    (it is a Paddle predictor like run_ocr, so it must not overlap one).

    Returns (clockwise degrees to rotate the page so it reads upright, score).
    PP-LCNet_x1_0_doc_ori reports how far the page is already rotated clockwise
    (label "90" = page was turned 90 degrees clockwise), so the correction is
    the complement. Any failure returns (0, 0.0): never rotate on a guess."""
    global _orientation_model
    try:
        import cv2
        import numpy as np

        if _orientation_model is None:
            with _orientation_init_lock:
                if _orientation_model is None:
                    from paddlex import create_model

                    _orientation_model = create_model("PP-LCNet_x1_0_doc_ori")
        img = cv2.imdecode(np.frombuffer(png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        res = list(_orientation_model.predict(img, batch_size=1))[0].json["res"]
        label = int(res["label_names"][0])
        score = float(res["scores"][0])
        return (360 - label) % 360, score
    except Exception as exc:  # noqa: BLE001
        global _last_orientation_log
        now = time.monotonic()
        if now - _last_orientation_log >= _ORIENTATION_LOG_EVERY_SECONDS:  # no log spam
            _last_orientation_log = now
            logger.warning(
                f"Orientation classifier failed, page left as is: class={type(exc).__name__} "
                f"msg={short_error_message(exc)}"
            )
        return 0, 0.0
