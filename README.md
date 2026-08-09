# ComfyUI-H3-PromptWriter

*English · [简体中文](README.zh-CN.md)*

A ComfyUI node that turns reference images plus a plain-language request into a
MiniMax H3 video prompt, using any **OpenAI-compatible API** and following the official
[h3-prompt-writing skill](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills).

Node: **H3 视频提示词撰写 (API)** — category `MiniMax H3`

```
                ┌──────────────────────────────────────────────┐
[image] ─┐      │ mode / duration                              │
[image] ─┼─────▶│ [✍️ generate]           [💾][📚][🔑]         │──▶ prompt (STRING)
         │      │ ┌──── query ────┐ ┌──── prompt ───────────┐  │
         └      │ │ what you want │ │ the written result,   │  │
                │ │ the video to  │ │ editable by hand —    │  │
                │ │ look like…    │ │ this is the output    │  │
                │ └───────────────┘ └───────────────────────┘  │
                └──────────────────────────────────────────────┘
```

## Install

From your `ComfyUI/custom_nodes/` directory:

```bash
git clone https://github.com/Ayin1412/ComfyUI-H3-PromptWriter.git
```

Restart ComfyUI. The dependencies (`requests`, `pillow`, `numpy`) ship with ComfyUI's
bundled environment, so you normally don't need to install anything; if something is
missing, run `pip install -r requirements.txt`.

## How it works

1. Click **🔑 API 设置** once to set the endpoint, model and key.
2. Pick a mode and wire your reference images into the left side — the image slots
   appear, disappear and rename themselves to match the mode.
3. Write your request in the left box, then click **✍️ 生成提示词**.

   This **does not go through ComfyUI's execution queue**. The frontend resolves your
   reference images to files on disk and hands them to a dedicated endpoint that runs on
   the web server's thread pool, so you can click it *while a video is rendering* — no
   waiting in line, and the running job is not interrupted. The written prompt lands in
   the right box, where you can edit it by hand.
4. When you later run the whole workflow, **the node never touches the API**: it just
   emits whatever is in the right box as `prompt`.

So *you* decide when an API call happens. Re-running the workflow neither overwrites
your hand edits nor burns tokens again.

### Where the images come from

To stay off the queue, the button needs images that already exist as files. It looks, in
order, at:

1. the preview attached to the upstream node (older ComfyUI frontends);
2. a filename widget on it — this covers `LoadImage` and friends;
3. that node's most recent output in `/history`, but only when the node type still
   matches, since node ids get reused across workflows.

If the immediate source has none of those, the search walks further upstream and tells
you which node it borrowed the image from. If the whole chain comes up empty — the image
only exists in VRAM, e.g. a fresh `VAEDecode` — it falls back to the queued path
(`partial_execution_targets`, so still only this node and its image ancestors run) and
warns you. Wiring a `LoadImage` in keeps it queue-free every time.

## What it actually sends

`references/base-en.txt`, `references/ref-en.txt` and `references/SKILL.md` are copied
verbatim from the official `skills/h3-prompt-writing/` directory. The node sends them as
the system prompt and appends this run's mode, duration and picture-numbering contract
(which image is `<Picture 1>`, which second it aligns to). The result therefore follows
the official field names, section order, and the conventions for shots, camera motion,
speaker IDs and `<d>` dialogue.

## The five modes

Image inputs are managed for you — they grow, shrink and relabel themselves per mode:

| Mode | Image inputs | Meaning |
| --- | --- | --- |
| `T2VA 纯文本` | none | Build the whole audiovisual timeline from text |
| `I2VA 首帧` | 1 | `<Picture 1>` is the first frame at 0.00 s |
| `FL2VA 首尾帧` | 2 | First frame `<Picture 1>`, then last frame `<Picture 2>` |
| `L2VA 尾帧` | 1 | `<Picture 1>` is the final frame; the path to it is inferred |
| `Ref2VA 多图参考` | any number | Fill one slot and the next appears; emits the six-section full-reference format |

- **A single image input may carry a batch.** Each frame expands into its own
  `<Picture N>`, so "several images under one ref" works in `Ref2VA`.
- A wrong image count fails fast with a message saying how many are missing — no wasted
  API call.
- Switching modes removes surplus slots, disconnecting them if needed.

## API settings

The node itself carries no API parameters. Everything lives in the **🔑 API 设置** panel
and is stored in `<ComfyUI>/user/default/h3_prompt_writer/config.json`, so it **never
ends up inside a workflow file**:

| Setting | Notes |
| --- | --- |
| `base_url` | A bare host or a `/v1` path both work — `/v1/chat/completions` is appended for you |
| `model` | Every mode except `T2VA` needs a vision-capable model. **获取模型** reads `{base_url}/models` and lets you pick from the list |
| `api_key` | The 👁 button toggles between plain text and dots; clear it and save to delete it |
| `temperature` / `max_tokens` | Sampling parameters |
| Timeout / retries | Rate limits, 5xx and timeouts are retried |
| Max image side | Images are downscaled before sending — smaller is cheaper and faster (default 1024) |
| Image detail | OpenAI's `detail` field; most other services ignore it |
| Extra requirements | Appended to every generation, e.g. "single shot only", "no dialogue" |

**🔌 测试连接** sends the shortest possible chat request using whatever is currently in
the form (no need to save first). On success it reports the model, latency and reply; on
failure it shows the raw API error. It only proves that text chat works — whether the
model can actually read images still needs a real generation.

Resolution order: **config file > environment variables**
(`H3_PROMPT_BASE_URL` / `OPENAI_BASE_URL`, `H3_PROMPT_API_KEY` / `OPENAI_API_KEY`,
`H3_PROMPT_MODEL`).

Common endpoints:

| Service | base_url | Vision-capable model |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| MiniMax | `https://api.minimaxi.com/v1` | `MiniMax-VL-01` |
| Alibaba DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-vl-max` |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-VL-72B-Instruct` |
| Local Ollama | `http://127.0.0.1:11434/v1` | `qwen2.5vl` |

## Saving prompts

- **💾 保存** stores the right-hand box in the prompt library
  (`<ComfyUI>/user/default/h3_prompt_writer/prompts.json`) and also writes a `.txt` copy
  under `output/h3_prompts/` with the mode and request as comments.
- **📚 提示词库** lets you search (name / mode / request / body), rename, tag, edit, copy
  and delete. "载入到节点" puts the body and its original request back into the node.

Records with identical text only get their timestamp bumped — the library does not
accumulate duplicates.

## License

The node code is MIT — see [LICENSE](LICENSE).

The three files under `references/` are **not covered by that license**. They are copied
verbatim from `skills/h3-prompt-writing/` in
[MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3) and remain the
copyright of MiniMax. See [references/README.md](references/README.md) for details.
