"""提示词库和 API 设置的 HTTP 接口，注册在 ComfyUI 自带的 PromptServer 上。

前端（web/h3_prompt_writer.js）通过这些接口读写 user/default/h3_prompt_writer/ 下的两个 json。
"""

import asyncio
import time

from aiohttp import web
from server import PromptServer

from . import config, h3_guide, images, library, modes, nodes, openai_client

routes = PromptServer.instance.routes


async def _json_body(request):
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


@routes.get("/h3_prompt/prompts")
async def list_prompts(request):
    return web.json_response({"items": library.load_all()})


@routes.post("/h3_prompt/save")
async def save_prompt(request):
    data = await _json_body(request)
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        return web.json_response({"error": "内容不能为空"}, status=400)
    item = library.add(
        text,
        name=str(data.get("name") or ""),
        tags=str(data.get("tags") or ""),
        mode=str(data.get("mode") or ""),
        query=str(data.get("query") or ""),
        model=config.settings()["model"],
    )
    # 顺手在 output/h3_prompts/ 下留一份 txt，方便直接拿去用
    path = library.export_txt(text, item["name"], item.get("mode", ""), item.get("query", ""))
    return web.json_response({"item": item, "path": path})


@routes.post("/h3_prompt/update")
async def update_prompt(request):
    data = await _json_body(request)
    item_id = data.get("id")
    if not item_id:
        return web.json_response({"error": "缺少 id"}, status=400)
    item = library.update(item_id, name=data.get("name"), text=data.get("text"),
                          tags=data.get("tags"))
    if item is None:
        return web.json_response({"error": "记录不存在"}, status=404)
    return web.json_response({"item": item})


@routes.post("/h3_prompt/delete")
async def delete_prompt(request):
    data = await _json_body(request)
    if not library.delete(data.get("id")):
        return web.json_response({"error": "记录不存在"}, status=404)
    return web.json_response({"ok": True})


@routes.get("/h3_prompt/config")
async def get_config(request):
    return web.json_response(config.public())


@routes.post("/h3_prompt/config")
async def set_config(request):
    # 不传的键保持原值；api_key 传空串 = 清空
    config.save(await _json_body(request))
    return web.json_response(config.public())


def _conn(data):
    """面板上还没保存的值优先，缺了就退回已保存的配置。"""
    saved = config.settings()
    return (
        str(data.get("base_url") or "").strip() or saved["base_url"],
        str(data.get("api_key") or "").strip() or saved["api_key"],
        str(data.get("model") or "").strip() or saved["model"],
        int(data.get("timeout") or saved["timeout"]),
    )


@routes.post("/h3_prompt/models")
async def fetch_models(request):
    """拉一遍接口的可用模型列表，给面板上的「获取模型」按钮用。"""
    base_url, api_key, _, timeout = _conn(await _json_body(request))
    try:
        items = await asyncio.to_thread(
            openai_client.list_models, base_url, api_key, min(timeout, 60))
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"items": items, "url": openai_client.models_url(base_url)})


def _write_prompt(mode, query, duration, refs):
    """在工作线程里干活：读图 → 拼 system prompt → 调接口。"""
    cfg = config.settings()
    if not cfg["api_key"]:
        raise ValueError("没有找到 API Key。点节点上的「API 设置」按钮填一次即可，"
                         "或者设置环境变量 OPENAI_API_KEY。")

    code = modes.mode_code(mode)
    urls = images.refs_to_data_urls(refs, max_side=cfg["max_image_side"])
    nodes.check_image_count(code, len(urls))

    system = h3_guide.build_system_prompt(code, len(urls), duration, cfg["extra_requirements"])
    user = openai_client.build_user_message(
        "Video request from the user (may be written in Chinese; the rewrite must still be "
        f"in English):\n{query.strip()}",
        urls,
        detail=cfg["image_detail"],
    )
    raw, _ = openai_client.complete(
        cfg["base_url"], cfg["api_key"], cfg["model"],
        [{"role": "system", "content": system}, user],
        temperature=cfg["temperature"], max_tokens=cfg["max_tokens"],
        timeout=cfg["timeout"], retries=cfg["retries"],
    )
    text = nodes.clean_prompt(raw)
    if not text:
        raise RuntimeError("模型返回内容为空，换个模型或在设置里调高 max_tokens 再试。")
    return text


@routes.post("/h3_prompt/generate")
async def generate(request):
    """写提示词。

    刻意不走 /prompt：这条接口跑在 aiohttp 自己的线程池上，和 ComfyUI 的执行队列没关系，
    所以正在出视频的时候点「生成提示词」也能立刻响应，不用排队，也不会插队打断出图。
    图片由前端以 {filename, subfolder, type} 的形式给过来，后端直接从磁盘读。
    """
    data = await _json_body(request)
    query = str(data.get("query") or "")
    if not query.strip():
        return web.json_response({"error": "请先写清楚你想要什么样的视频"}, status=400)

    try:
        duration = float(data.get("duration") or 6.0)
    except (TypeError, ValueError):
        duration = 6.0

    refs = data.get("images")
    refs = refs if isinstance(refs, list) else []

    try:
        text = await asyncio.to_thread(
            _write_prompt, data.get("mode"), query, duration, refs)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({"prompt": text})


@routes.post("/h3_prompt/test")
async def test_connection(request):
    """发一句最短的对话，确认地址 / key / 模型这条链路是通的。"""
    base_url, api_key, model, timeout = _conn(await _json_body(request))
    if not api_key:
        return web.json_response({"error": "还没填 API Key"}, status=400)
    if not model:
        return web.json_response({"error": "还没填模型名"}, status=400)

    started = time.perf_counter()
    try:
        reply, _ = await asyncio.to_thread(
            openai_client.complete,
            base_url, api_key, model,
            [{"role": "user", "content": "Reply with exactly: OK"}],
            0.0, 16, min(timeout, 60), 0,
        )
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response({
        "ok": True,
        "model": model,
        "ms": int((time.perf_counter() - started) * 1000),
        "reply": reply.strip()[:80],
    })
