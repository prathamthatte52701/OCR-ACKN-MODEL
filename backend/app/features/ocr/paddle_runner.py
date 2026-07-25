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
import threading
from typing import Any

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


def _get_ocr() -> Any:
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
                    use_doc_orientation_classify=False,
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


def run_ocr(image_path: str) -> str | None:
    """Blocking call - invoke via asyncio.to_thread from async code. Reuses
    the cached PaddleOCR singleton instead of loading the model fresh."""
    try:
        ocr = _get_ocr()
        results = ocr.predict(image_path)
        lines: list[str] = []
        for r in results:
            texts = r.json.get("res", {}).get("rec_texts", [])
            lines.extend(t for t in texts if t and t.strip())
        return "\n".join(lines) or None
    except Exception:  # noqa: BLE001
        return None
