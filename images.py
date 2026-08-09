"""把图片变成 chat completions 能吃的 data URL。

两条来源：
  * IMAGE 张量——节点在工作流里跑到时拿到的（排队执行那条路）
  * 磁盘文件——前端只给了 {filename, subfolder, type} 这样的引用（不排队那条路）
"""

import base64
import io
import os

import numpy as np
from PIL import Image

try:
    import folder_paths
except ImportError:  # pragma: no cover - 脱离 ComfyUI 单跑时
    folder_paths = None


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


def _encode(img, max_side, quality):
    """PIL.Image → data URL。用 JPEG，同画质下体积远小于 PNG，视觉模型也不在乎无损。"""
    buf = io.BytesIO()
    _shrink(img, max_side).save(buf, format="JPEG", quality=int(quality), optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def ref_to_data_url(ref, max_side=1024, quality=90):
    """{"filename", "subfolder", "type"} → data URL。

    这就是 ComfyUI /view 接口那套参数，所以前端不管是 LoadImage 的文件名还是某个节点
    已经跑出来的预览图，都能直接把引用丢过来。路径校验沿用 ComfyUI 自己的实现，
    防止拿这条接口去读工作目录以外的文件。
    """
    if folder_paths is None:
        raise RuntimeError("拿不到 ComfyUI 的目录配置")
    if not isinstance(ref, dict):
        raise ValueError("图片引用格式不对")

    filename = str(ref.get("filename") or "").strip()
    if not filename:
        raise ValueError("图片引用里没有 filename")

    kind = str(ref.get("type") or "input").strip().lower()
    base = folder_paths.get_directory_by_type(kind)
    if base is None:
        raise ValueError(f"未知的图片来源类型 {kind!r}")

    subfolder = str(ref.get("subfolder") or "").strip()
    if subfolder:
        base = os.path.join(base, subfolder)

    # get_annotated_filepath 会处理 "name [input]" 这种标注，并挡掉路径穿越
    path = folder_paths.get_annotated_filepath(filename, base)
    if not os.path.isfile(path):
        raise ValueError(f"找不到图片文件：{filename}")

    with Image.open(path) as img:
        img.load()
        if img.mode != "RGB":
            img = img.convert("RGB")
        return _encode(img, max_side, quality)


def refs_to_data_urls(refs, max_side=1024, quality=90):
    return [ref_to_data_url(r, max_side, quality) for r in (refs or [])]


def frames_to_data_urls(image_batch, max_side=1024, quality=90):
    """一个 IMAGE 输入（可能是 batch）→ 每帧一个 data URL，顺序保持不变。"""
    batch = image_batch
    if hasattr(batch, "detach"):
        batch = batch.detach().cpu()
    batch = np.asarray(batch)
    if batch.ndim == 3:  # 单帧也当成 batch 处理
        batch = batch[None, ...]

    return [_encode(_to_pil(frame), max_side, quality) for frame in batch]
