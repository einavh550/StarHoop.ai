"""Milestone 2 — Build the real CV image and warm-load the models on Modal.

This proves the heavy environment (SAM-2 native build + Roboflow inference +
SigLIP) works on a Modal GPU, and that model weights load once per container via
``@modal.enter()`` instead of on every request. No database, no FastAPI yet.

Two ways to run it:

1) Validate the IMAGE BUILD + SAM-2 only (no secret required):

       modal run -m modal_app.cv_app::main

   This builds the cached image and loads the SAM-2 checkpoint on a GPU. It does
   NOT touch Roboflow/HuggingFace, so it works before you create any secret. Use
   it to confirm the expensive native build succeeds.

   Note: use the ``-m`` module form (not ``modal run modal_app/cv_app.py``).
   Modal 1.0 dropped implicit source auto-mounting, so the package must be
   shipped via ``add_local_python_source("modal_app")`` (see images.py) AND
   referenced by its module path so ``from modal_app.images import ...`` resolves
   inside the container.

2) Full warm-up of ALL FOUR models (requires the secret):

   First create the Modal secret once with your real tokens:

       modal secret create hoopstar-secrets HF_TOKEN=<hf_token> ROBOFLOW_API_KEY=<rf_key>

   Then run the warmup entrypoint:

       modal run -m modal_app.cv_app::warmup

   Expected: a report showing detector/ocr/sam2/team_classifier all loaded and
   ``cuda_available=True``. That is the Milestone 2 PASS condition.
"""

from __future__ import annotations

import modal

from modal_app.images import (
    NUMBER_RECOGNITION_MODEL_ID,
    PLAYER_DETECTION_MODEL_ID,
    SAM2_CHECKPOINT,
    SAM2_CONFIG,
    cv_image,
    hoopstar_secret,
)

app = modal.App("hoopstar-cv")


@app.function(image=cv_image, gpu="L4", timeout=600)
def check_imports() -> dict:
    """Validate the image build + SAM-2 without needing any secret.

    Imports every heavy dependency and loads the baked-in SAM-2 checkpoint on the
    GPU. This is the riskiest part of the build (native SAM-2), so passing here
    means the environment itself is sound.
    """
    import torch
    import supervision as sv  # noqa: F401
    import inference  # noqa: F401
    import sports  # noqa: F401
    from sam2.build_sam import build_sam2_camera_predictor

    cuda = torch.cuda.is_available()
    predictor = build_sam2_camera_predictor(SAM2_CONFIG, SAM2_CHECKPOINT)

    report = {
        "cuda_available": bool(cuda),
        "device_name": str(torch.cuda.get_device_name(0)) if cuda else None,
        "torch_version": str(torch.__version__),
        "supervision_version": str(sv.__version__),
        "sam2_predictor_loaded": predictor is not None,
    }
    print(f"[hoopstar-cv] check_imports report: {report}")
    return report


@app.cls(image=cv_image, gpu="L4", secrets=[hoopstar_secret], timeout=900)
class BasketballModels:
    """Warm-loads all four models once when the container starts.

    This is the class that Milestone 3/4 will extend with the real
    ``process_video`` inference method. For now it only loads + reports.
    """

    @modal.enter()
    def load(self) -> None:
        import torch
        from inference import get_model
        from sam2.build_sam import build_sam2_camera_predictor
        from sports import TeamClassifier

        self.cuda = torch.cuda.is_available()

        # RF-DETR player detector + SmolVLM2 jersey OCR (Roboflow, need API key).
        self.detector = get_model(model_id=PLAYER_DETECTION_MODEL_ID)
        self.ocr = get_model(model_id=NUMBER_RECOGNITION_MODEL_ID)

        # SAM-2 real-time predictor (checkpoint baked into the image).
        self.predictor = build_sam2_camera_predictor(SAM2_CONFIG, SAM2_CHECKPOINT)

        # SigLIP-based team classifier (needs HF_TOKEN). Fitted per-video later.
        self.team_classifier = TeamClassifier(device="cuda")

        print("[hoopstar-cv] all four models warm-loaded")

    @modal.method()
    def verify(self) -> dict:
        import torch

        report = {
            "cuda_available": bool(self.cuda),
            "device_name": str(torch.cuda.get_device_name(0)) if self.cuda else None,
            "detector_loaded": self.detector is not None,
            "ocr_loaded": self.ocr is not None,
            "sam2_predictor_loaded": self.predictor is not None,
            "team_classifier_loaded": self.team_classifier is not None,
        }
        print(f"[hoopstar-cv] verify report: {report}")
        return report


@app.local_entrypoint()
def main() -> None:
    """Default: validate the image build + SAM-2 (no secret needed)."""
    report = check_imports.remote()
    print("Image/SAM-2 validation:", report)
    if report.get("cuda_available") and report.get("sam2_predictor_loaded"):
        print(
            "Milestone 2 (build) PASSED: image builds and SAM-2 loads on GPU.\n"
            "Next: create the 'hoopstar-secrets' Modal secret, then run\n"
            "    modal run modal_app/cv_app.py::warmup"
        )
    else:
        print("Milestone 2 (build) FAILED: see report above.")


@app.local_entrypoint()
def warmup() -> None:
    """Full warm-up of all four models (requires the hoopstar-secrets secret)."""
    report = BasketballModels().verify.remote()
    print("Full model warm-up report:", report)
    ok = all(
        report.get(k)
        for k in (
            "cuda_available",
            "detector_loaded",
            "ocr_loaded",
            "sam2_predictor_loaded",
            "team_classifier_loaded",
        )
    )
    if ok:
        print("Milestone 2 PASSED: all four models warm-loaded on Modal GPU.")
    else:
        print("Milestone 2 FAILED: one or more models did not load (see report).")
