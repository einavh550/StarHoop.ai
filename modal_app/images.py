"""Milestone 2 — Modal image + secret definitions for the basketball CV pipeline.

This module declaratively reproduces the Google Colab environment from
``src/app/cv/basketball_ai_how_to_detect_track_and_identify_basketball_players.py``
as a cached ``modal.Image``. Everything that used to be a ``!pip``/``!git clone``
cell in Colab lives here instead, so it builds once and is reused on every run.

What the image contains:
  * System libs: git, wget, ffmpeg (video re-encode), OpenGL libs for OpenCV.
  * Roboflow ``inference-gpu`` (RF-DETR detector + SmolVLM2 jersey OCR) installed
    FIRST so it owns the PyTorch (CUDA) build — we no longer pin torch, which kept
    the env internally consistent (see images.py build notes).
  * SAM-2 real-time fork (Gy920/segment-anything-2-real-time) installed LAST and
    non-editable (with its optional CUDA extension stripped), so its ``sam2``
    package wins over inference's ``rf-sam-2``. The ``sam2.1_hiera_large``
    checkpoint is baked into the image.
  * ``supervision==0.27.0``, the Roboflow ``sports`` fork (TeamClassifier/SigLIP,
    court tooling), ``transformers``, ``num2words``, ``gdown``.

Secrets (created by the user once, see cv_app.py docstring):
  * HF_TOKEN          -> pull SigLIP from HuggingFace (TeamClassifier)
  * ROBOFLOW_API_KEY  -> pull RF-DETR + SmolVLM2 from Roboflow Universe
"""

from __future__ import annotations

import modal

# --- SAM-2 real-time fork location + checkpoint -----------------------------
SAM2_REPO = "https://github.com/Gy920/segment-anything-2-real-time.git"
SAM2_DIR = "/opt/sam2rt"
# Hydra resolves the config through the installed ``sam2`` package, so this stays
# a package-relative path exactly like the original Colab notebook used.
SAM2_CONFIG = "configs/sam2.1/sam2.1_hiera_l.yaml"
# The checkpoint, by contrast, must be an absolute filesystem path.
SAM2_CHECKPOINT = f"{SAM2_DIR}/checkpoints/sam2.1_hiera_large.pt"
SAM2_CHECKPOINT_URL = (
    "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"
)

# --- Model IDs (Roboflow Universe) ------------------------------------------
PLAYER_DETECTION_MODEL_ID = "basketball-player-detection-3-ycjdo/4"
NUMBER_RECOGNITION_MODEL_ID = "basketball-jersey-numbers-ocr/3"


cv_image = (
    # CUDA base image. We deliberately do NOT compile SAM-2's CUDA extension
    # anymore (see the final SAM-2 step), so nvcc is not strictly required — but we
    # keep this CUDA 12.1 base because its apt layer is already cached and it
    # supplies the system CUDA runtime libs that inference-gpu's onnxruntime-gpu
    # expects. add_python gives us the 3.11 interpreter on top.
    modal.Image.from_registry(
        "nvidia/cuda:12.1.1-cudnn8-devel-ubuntu22.04", add_python="3.11"
    )
    .apt_install(
        "git",
        "wget",
        "build-essential",
        "gcc",
        "g++",
        "ffmpeg",
        "libgl1",
        "libglib2.0-0",
    )
    # Clone the SAM-2 real-time fork and bake in the large checkpoint NOW, but do
    # NOT install SAM-2 here. It is installed LAST (after inference-gpu) so that our
    # `sam2` package is the final writer of site-packages/sam2 and wins over the
    # `rf-sam-2` that inference-gpu drags in. See the final run_commands.
    .run_commands(
        f"git clone {SAM2_REPO} {SAM2_DIR}",
        f"mkdir -p {SAM2_DIR}/checkpoints",
        # Download only the large checkpoint instead of the whole download_ckpts.sh set.
        f"wget -q {SAM2_CHECKPOINT_URL} -O {SAM2_CHECKPOINT}",
    )
    # Pin the C/C++ compilers BEFORE installing inference-gpu. inference-models
    # pulls `pycuda`, which has no prebuilt wheel and compiles a C++ extension at
    # install time. Without CXX set, pycuda's build defaults to `clang++`, which is
    # not in this image (we install gcc/g++ via build-essential), so the wheel build
    # dies with "command 'clang++' failed: No such file or directory". Pointing
    # CC/CXX at gcc/g++ makes pycuda (and any other source build) use the compilers
    # we actually have. This env is placed after the clone/checkpoint layers so they
    # stay cached, and applies to every build step below.
    .env({"CC": "gcc", "CXX": "g++"})
    # Pin torch to a CUDA 12.4 build in the SAME command that installs inference. If
    # torch is left free, the resolver pulls the newest wheel (torch 2.12.0+cu130,
    # i.e. CUDA 13.0). That breaks the SmolVLM2 jersey-OCR model: it loads through
    # transformers with bitsandbytes quantization, and the bitsandbytes wheel only
    # ships per-CUDA binaries (libbitsandbytes_cuda124.so, _cuda121.so, ...) — there
    # is NO _cuda130.so yet, so model-weight conversion dies with "Configured CUDA
    # binary not found at .../libbitsandbytes_cuda130.so".
    #
    # Pinning torch to +cu124 (the exact CUDA inference itself targets via its
    # `torch-cu124` extra, and what the original Colab used) makes bitsandbytes find
    # its cuda124 binary. We pin it HERE, alongside inference, as a HARD pin so pip's
    # resolver cannot silently upgrade torch back to cu130 to satisfy some other
    # package (e.g. transformers): if a real conflict exists pip fails loudly instead.
    # This is safe because SAM-2 no longer compiles against torch (its extension is
    # stripped below and it installs with --no-deps), so nothing is ABI-coupled to
    # torch's version. extra_index_url adds PyTorch's cu124 wheel index while keeping
    # the default index for every other dependency. setuptools/wheel build SAM-2 with
    # --no-build-isolation; hydra-core + iopath are SAM-2 runtime deps we add here so
    # the SAM-2 install can use --no-deps and never perturb this torch.
    .pip_install(
        "torch==2.6.0+cu124",
        "torchvision==0.21.0+cu124",
        "inference-gpu",
        "supervision==0.27.0",
        "transformers",
        "num2words",
        "gdown",
        "setuptools",
        "wheel",
        "hydra-core>=1.3.2",
        "iopath>=0.1.10",
        extra_index_url="https://download.pytorch.org/whl/cu124",
    )
    # Roboflow sports fork: TeamClassifier (SigLIP), court config, ShotEventTracker.
    .pip_install("git+https://github.com/roboflow/sports.git@feat/basketball")
    # Install the SAM-2 real-time fork LAST, non-editable, with two key tweaks:
    #   * `sed ... ext_modules=[]` — the fork's setup.py compiles a CUDA extension
    #     (sam2._C from connected_components.cu) UNCONDITIONALLY. That extension is
    #     ONLY a connected-components optimization used by fill_holes_in_mask_scores,
    #     which already try/excepts a pure-PyTorch fallback ("OK to ignore"). The
    #     `_C` import is lazy (inside get_connected_components), so `import sam2` and
    #     build_sam2_camera_predictor never need it. Compiling it would require nvcc
    #     to match torch's CUDA (impossible: inference pulls cu13 onto a 12.1 base),
    #     so we strip it and avoid nvcc entirely.
    #   * `--force-reinstall --no-deps` — write OUR sam2 into site-packages as the
    #     LAST writer so it beats inference's `rf-sam-2` (which lacks
    #     build_sam2_camera_predictor). --no-deps guarantees torch and inference's
    #     other resolved deps are left exactly as inference set them.
    # --no-build-isolation lets setup.py import the already-installed torch.
    .run_commands(
        f"cd {SAM2_DIR} "
        f"&& sed -i 's/ext_modules=get_extensions()/ext_modules=[]/' setup.py "
        f"&& pip install . --no-build-isolation --no-deps --force-reinstall"
    )
    # Route ONNX Runtime to the GPU, matching the Colab notebook.
    .env({"ONNXRUNTIME_EXECUTION_PROVIDERS": "[CUDAExecutionProvider]"})
    # Ship our own package into the container. As of Modal 1.0 the old implicit
    # auto-mounting of local source is gone, so without this the container only
    # gets the flattened entrypoint file and `from modal_app.images import ...`
    # fails with ModuleNotFoundError. This is a lightweight final mount layer; it
    # does NOT invalidate the cached native build above. Run with the module form
    # `modal run -m modal_app.cv_app::main` so the package name resolves.
    .add_local_python_source("modal_app")
)


# Reference to the user-created Modal secret holding HF_TOKEN + ROBOFLOW_API_KEY.
# Create it once with:
#   modal secret create hoopstar-secrets HF_TOKEN=<hf> ROBOFLOW_API_KEY=<rf>
hoopstar_secret = modal.Secret.from_name("hoopstar-secrets")
