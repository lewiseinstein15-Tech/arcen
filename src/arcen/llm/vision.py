"""Vision — a capability probe, not a promise.

GLM-5.4's generalized coding leans on vision: reading a rendered UI,
checking a 3D scene, judging generated video frames. ARCEN's providers may
or may not accept images, and a chat-completions call that silently drops
the image would produce a confident answer about nothing.

So this module refuses rather than guesses:

- :func:`supports_vision` checks the configured model against a known list
  of multimodal families (extendable via ``provider.vision_model``);
- :func:`load_image` validates the file by magic bytes and size before it
  is base64-encoded;
- :func:`describe_image` raises :class:`VisionUnsupported` when the model
  cannot take images, so the caller can say "this provider cannot see" on
  the stream instead of inventing a description.

Video is deliberately absent: no supported provider accepts video frames
through this interface, and pretending otherwise would be the exact failure
mode this module exists to prevent. Extracting frames with a tool and
describing each frame works today and is documented as the workaround.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

MAX_IMAGE_BYTES = 4 * 1024 * 1024

# Substrings of model ids known to accept image content parts. This is a
# heuristic gate, not a capability API — providers do not expose one.
VISION_HINTS: tuple[str, ...] = (
    "gpt-4o",
    "gpt-4.1",
    "gpt-5",
    "claude-3",
    "claude-4",
    "claude-sonnet",
    "claude-opus",
    "gemini",
    "qwen-vl",
    "qwen2-vl",
    "qwen2.5-vl",
    "qwen3-vl",
    "llava",
    "pixtral",
    "glm-4v",
    "glm-4.5v",
    "internvl",
    "molmo",
    "llama-3.2-vision",
    "llama-4",
)

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


class VisionError(ValueError):
    """The image could not be used."""


class VisionUnsupported(VisionError):
    """The configured model does not accept images."""


def supports_vision(model: str | None) -> bool:
    """True when ``model`` is a known multimodal model id."""
    if not model:
        return False
    lowered = model.lower()
    return any(hint in lowered for hint in VISION_HINTS)


def _sniff(data: bytes) -> str:
    for magic, mime in _MAGIC:
        if data.startswith(magic):
            return mime
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    raise VisionError("unsupported image format (png, jpeg, gif, webp only)")


def load_image(path: str | Path, *, max_bytes: int = MAX_IMAGE_BYTES) -> tuple[str, str]:
    """Read an image and return ``(data_url, mime)``.

    Validates by content, not by extension: a ``.png`` that is not a PNG is
    rejected, and anything larger than ``max_bytes`` is refused before it is
    base64-inflated into the prompt.
    """
    file = Path(path)
    if not file.is_file():
        raise VisionError(f"not a file: {file}")
    size = file.stat().st_size
    if size == 0:
        raise VisionError(f"empty image: {file}")
    if size > max_bytes:
        raise VisionError(f"image is {size} bytes; limit is {max_bytes}")
    data = file.read_bytes()
    mime = _sniff(data)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{encoded}", mime


def describe_image(
    client: Any,
    image_path: str | Path,
    prompt: str = "Describe what this image shows. Report only what is visible.",
    *,
    role: str = "verifier",
    model: str | None = None,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> str:
    """Ask a multimodal model about one image.

    ``model`` overrides the probe (``provider.vision_model``); when neither
    is set the role's configured model is checked. Raises
    :class:`VisionUnsupported` when the model cannot accept images and
    :class:`VisionError` for a bad file — never returns a fabricated
    description.
    """
    if client is None:
        raise VisionUnsupported("no model provider is configured")

    resolved = (model or "").strip()
    if not resolved:
        try:
            resolved = client.model_for(role)
        except Exception as exc:
            raise VisionUnsupported(f"no model configured for role {role!r}") from exc
    if not supports_vision(resolved):
        raise VisionUnsupported(
            f"model {resolved!r} is not a known multimodal model; "
            "set provider.vision_model to a vision-capable model"
        )

    data_url, _mime = load_image(image_path, max_bytes=max_bytes)
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }
    ]
    response = client.complete(role, messages, temperature=0.0)
    return str(getattr(response, "text", "") or "")
