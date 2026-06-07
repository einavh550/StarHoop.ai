"""Milestone 1 — Hello-Modal.

Smallest possible Modal app that proves we can run a GPU container in the cloud.
No models, no database, no FastAPI. This is purely an environment sanity check.

Run it locally (after `modal setup` has been completed) with:

    modal run modal_app/app.py

Expected result: the function executes on a remote T4 GPU and reports that CUDA
is available, printing the GPU name. If you see `cuda_available=True`, the Modal
GPU path works and we can proceed to Milestone 2 (the real image build).
"""

from __future__ import annotations

import modal

# A minimal image is enough for M1: we only need torch to query CUDA.
# In Milestone 2 this grows into the full RF-DETR / SAM-2 / OCR image.
image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "torch==2.3.1",
)

app = modal.App("hoopstar-hello", image=image)


@app.function(gpu="T4")
def check_gpu() -> dict:
    """Run on a remote T4 GPU and report whether CUDA is wired up correctly."""
    import torch

    cuda_available = torch.cuda.is_available()
    info = {
        "cuda_available": cuda_available,
        # Cast torch values to plain str/int so the result deserializes locally
        # without requiring torch to be installed on the calling machine.
        "torch_version": str(torch.__version__),
        "device_count": int(torch.cuda.device_count()) if cuda_available else 0,
        "device_name": str(torch.cuda.get_device_name(0)) if cuda_available else None,
    }
    print(f"[hoopstar-hello] GPU check: {info}")
    return info


@app.local_entrypoint()
def main() -> None:
    """Local entrypoint invoked by `modal run`. Calls the remote GPU function."""
    result = check_gpu.remote()
    print("Remote GPU reported:", result)
    if result.get("cuda_available"):
        print("Milestone 1 PASSED: Modal GPU is reachable and CUDA is available.")
    else:
        print("Milestone 1 FAILED: function ran but CUDA was not available.")
