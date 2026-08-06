"""最小的 OpenAI 兼容 chat completions 客户端。

只用 requests，不额外依赖 openai SDK：这样任何"OpenAI 兼容"的服务
（OpenAI / MiniMax / 硅基流动 / DeepSeek / OpenRouter / Ollama / vLLM / 各种中转）
填个 base_url 就能用。
"""

import json
import time

import requests

RETRY_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


_SUFFIX = "/chat/completions"
_ROOTS = ("/v1", "/v1beta", "/openai")


def api_root(base_url):
    """把用户填的 base_url 归一成接口根地址。

    三种常见写法都认：
        https://api.openai.com            → https://api.openai.com/v1
        https://api.openai.com/v1         → 原样
        https://xxx/v1/chat/completions   → https://xxx/v1
    """
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("base_url 不能为空")
    if url.endswith(_SUFFIX):
        url = url[: -len(_SUFFIX)].rstrip("/")
    if not url.endswith(_ROOTS):
        url += "/v1"
    return url


def chat_completions_url(base_url):
    return api_root(base_url) + _SUFFIX


def models_url(base_url):
    return api_root(base_url) + "/models"


def _headers(api_key):
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def list_models(base_url, api_key, timeout=30):
    """GET /models，返回模型 id 列表。"""
    url = models_url(base_url)
    try:
        resp = requests.get(url, headers=_headers(api_key), timeout=float(timeout))
    except requests.RequestException as e:
        raise RuntimeError(f"请求 {url} 失败：{e}") from e
    if resp.status_code != 200:
        raise RuntimeError(f"接口返回 {resp.status_code}：{_error_text(resp)}")

    try:
        data = resp.json()
    except ValueError:
        raise RuntimeError(f"{url} 返回的不是 JSON")

    # 标准形状是 {"data": [{"id": ...}]}，也有服务直接给一个列表
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise RuntimeError(f"没看懂 {url} 的返回结构")

    ids = []
    for item in items:
        mid = item.get("id") or item.get("model") or item.get("name") if isinstance(item, dict) else item
        if isinstance(mid, str) and mid.strip() and mid not in ids:
            ids.append(mid.strip())
    return sorted(ids, key=str.lower)


def build_user_message(text, image_urls, detail="auto"):
    """文本 + 图片拼成一条多模态 user 消息；没图时退回纯字符串，兼容不支持 parts 的服务。"""
    if not image_urls:
        return {"role": "user", "content": text}
    parts = [{"type": "text", "text": text}]
    for url in image_urls:
        image_url = {"url": url}
        if detail and detail != "auto":
            image_url["detail"] = detail
        parts.append({"type": "image_url", "image_url": image_url})
    return {"role": "user", "content": parts}


def _extract_text(data):
    """取回复正文。content 可能是字符串，也可能是 parts 列表。"""
    try:
        choice = data["choices"][0]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(f"接口返回里没有 choices：{json.dumps(data, ensure_ascii=False)[:500]}")

    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    if not content:
        # 有些推理模型只填了 reasoning_content，正文是空的
        content = message.get("reasoning_content") or ""
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError(
            "模型返回了空内容"
            + (f"（finish_reason={choice.get('finish_reason')}）" if choice.get("finish_reason") else "")
        )
    return content


def _error_text(resp):
    try:
        data = resp.json()
    except Exception:
        return (resp.text or "")[:500]
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or err)[:500]
    return json.dumps(data, ensure_ascii=False)[:500]


def complete(base_url, api_key, model, messages, temperature=0.7, max_tokens=4096,
             timeout=120, retries=2, extra_body=None):
    """发一次请求，返回 (正文, 原始 JSON)。失败会重试可恢复的错误。"""
    url = chat_completions_url(base_url)
    headers = _headers(api_key)

    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "stream": False,
    }
    if max_tokens and int(max_tokens) > 0:
        payload["max_tokens"] = int(max_tokens)
    if isinstance(extra_body, dict):
        payload.update(extra_body)

    last_err = None
    for attempt in range(int(retries) + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=float(timeout))
        except requests.RequestException as e:
            last_err = f"请求 {url} 失败：{e}"
        else:
            if resp.status_code == 200:
                return _extract_text(resp.json()), resp.json()
            last_err = f"接口返回 {resp.status_code}：{_error_text(resp)}"
            if resp.status_code not in RETRY_STATUS:
                break

        if attempt < int(retries):
            time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(last_err or "请求失败")
