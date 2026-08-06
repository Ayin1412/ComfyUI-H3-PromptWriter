"""把 ComfyUI 的 IMAGE 张量转成 chat completions 能吃的 data URL。"""

import base64
import io

import numpy as np
from PIL import Image


def _to_pil(frame):
    """单帧 [H, W, C]（float 0~1 或 uint8）→ PIL.Image。"""
    arr = frame
    if hasattr(arr, "detach"):  # torch.Tensor
        arr = arr.detach().cpu().numpy()
    arr = np.asarray(arr)
    if arr.ndim == 2:
        arr = arr[..., None]
    if arr.dtype != np.uint8:
        arr = np.clip(arr.astype(np.float32) * 255.0, 0, 255).astype(np.uint8)
    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    elif arr.shape[-1] == 4:
        arr = arr[..., :3]  # 传给模型不需要 alpha
    return Image.fromarray(arr, mode="RGB")


def _shrink(img, max_side):
    """按最长边等比缩小，只缩不放——图越大 token 越贵，也更容易超时。"""
    if max_side and max_side > 0 and max(img.size) > max_side:
        scale = max_side / float(max(img.size))
        size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        img = img.resize(size, Image.LANCZOS)
    return img


def frames_to_data_urls(image_batch, max_side=1024, quality=90):
    """一个 IMAGE 输入（可能是 batch）→ 每帧一个 data URL，顺序保持不变。

    用 JPEG，因为同样画质下体积远小于 PNG，视觉模型也不在乎无损。
    """
    batch = image_batch
    if hasattr(batch, "detach"):
        batch = batch.detach().cpu()
    batch = np.asarray(batch)
    if batch.ndim == 3:  # 单帧也当成 batch 处理
        batch = batch[None, ...]

    urls = []
    for frame in batch:
        img = _shrink(_to_pil(frame), max_side)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=int(quality), optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        urls.append(f"data:image/jpeg;base64,{b64}")
    return urls
