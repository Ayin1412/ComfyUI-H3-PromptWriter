# ComfyUI-H3-PromptWriter

调用任意 **OpenAI 兼容接口**，按 MiniMax 官方 [h3-prompt-writing skill](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills) 的规范，
把「参考图 + 你的大白话需求」写成可以直接喂给 H3 的视频提示词。

节点：**H3 视频提示词撰写 (API)**（分类 `MiniMax H3`）

```
                ┌──────────────────────────────────────────────┐
[图片] ─┐       │ mode / duration                              │
[图片] ─┼──────▶│ [✍️ 生成提示词]      [💾][📚][🔑]            │──▶ prompt (STRING)
        │       │ ┌──需求 query──┐ ┌──提示词 prompt──────────┐ │
        └       │ │ 你想要什么样 │ │ 写好的结果，可直接手改   │ │
                │ │ 的视频…      │ │ 节点输出的就是它         │ │
                │ └──────────────┘ └──────────────────────────┘ │
                └──────────────────────────────────────────────┘
```

## 怎么用

1. 点 **🔑 API 设置** 填一次接口地址、模型和 Key。
2. 选模式，把参考图接到左边（槽位会跟着模式自己变）。
3. 左边框写需求 → 点 **✍️ 生成提示词**。

   这时只会跑这个节点和它上游的图片节点（用的是 ComfyUI 的 `partial_execution_targets`），
   **不会带着采样器一起跑**。写好的提示词出现在右边的框里，可以直接手改。
4. 之后正常运行工作流：**节点不碰 API**，直接把右边框里的内容作为 `prompt` 输出。

所以调 API 的时机完全由你点按钮决定，反复跑工作流既不会覆盖你的手改，也不会重复烧 token。

## 它做了什么

`references/` 下的 `base-en.txt`、`ref-en.txt`、`SKILL.md` 原样取自官方仓库的
`skills/h3-prompt-writing/`，节点把它们作为 system prompt 发给模型，再补上本次的模式、
时长和图片编号约定（哪张图是 `<Picture 1>`、对齐到第几秒），所以产出的提示词遵守官方
的字段名、字段顺序、镜头/机位/说话人/`<d>` 台词等全部写法约定。

## 五种模式与图片输入

左侧的图片输入会**跟着模式自动增减和改名**，不用手动管：

| 模式 | 图片输入 | 含义 |
| --- | --- | --- |
| `T2VA 纯文本` | 无 | 纯文字生成完整音画时间线 |
| `I2VA 首帧` | 1 张 | `<Picture 1>` = 0.00 秒的首帧 |
| `FL2VA 首尾帧` | 2 张 | 依次是首帧 `<Picture 1>`、尾帧 `<Picture 2>` |
| `L2VA 尾帧` | 1 张 | `<Picture 1>` = 结尾那一帧，倒推出前面的过程 |
| `Ref2VA 多图参考` | 不限 | 接满一个就自动长出下一个；输出六段式全参考格式 |

- **一个图片输入可以接多图 batch**（比如 `Image Batch` / 多图加载器），会按帧展开成
  `<Picture 1>`、`<Picture 2>`…，所以 Ref2VA 下"一个 ref 里放多张图"是支持的。
- 张数不对会直接报错说明差几张，不会浪费一次 API 调用。
- 换模式时多余的槽位会被拆掉（连着线也会拆），换回来重接即可。

## API 设置

节点上不放任何 API 参数，全部在 **🔑 API 设置** 面板里，存在
`<ComfyUI>/user/default/h3_prompt_writer/config.json`，**不会进工作流文件**：

| 项 | 说明 |
| --- | --- |
| `base_url` | 写到 `/v1` 或只写域名都行，会自动补成 `/v1/chat/completions` |
| `model` | 除 T2VA 外都必须选支持图片输入的模型。旁边的 **获取模型** 会读 `{base_url}/models`，拉回来的列表可以直接选 |
| `api_key` | 右边的 👁 切换明文 / 圆点显示；清空再保存就是删掉 |
| `temperature` / `max_tokens` | 采样参数 |
| 单次超时 / 失败重试次数 | 限流、5xx、超时会按次数重试 |
| 发图前缩到最长边 | 越小越省 token、越快，默认 1024 |
| 图片细节档位 | OpenAI 的 `detail`，非 OpenAI 服务一般忽略 |
| 额外约束 | 每次生成都附加，例如「只用一个镜头」「不要台词」 |

面板底下的 **🔌 测试连接** 会用当前框里填的值（不用先保存）发一句最短的对话，
通了会显示模型名、耗时和回复；不通会把接口的原始错误显示出来。它只验证文字对话，
模型能不能读图还是要靠实际生成一次。

优先级：**配置文件 > 环境变量**
（`H3_PROMPT_BASE_URL` / `OPENAI_BASE_URL`、`H3_PROMPT_API_KEY` / `OPENAI_API_KEY`、`H3_PROMPT_MODEL`）。

常见的填法：

| 服务 | base_url | 带视觉的模型示例 |
| --- | --- | --- |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| MiniMax | `https://api.minimaxi.com/v1` | `MiniMax-VL-01` |
| 阿里百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-vl-max` |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `Qwen/Qwen2.5-VL-72B-Instruct` |
| 本地 Ollama | `http://127.0.0.1:11434/v1` | `qwen2.5vl` |

## 保存提示词

- **💾 保存**：把右边框里的内容存进提示词库
  （`<ComfyUI>/user/default/h3_prompt_writer/prompts.json`），
  同时在 `output/h3_prompts/` 下另存一份带模式和需求注释的 `.txt`。
- **📚 提示词库**：搜索（名称 / 模式 / 需求 / 正文）、改名、打标签、编辑正文、复制、删除；
  「载入到节点」会把正文和当初的需求一起放回节点。

内容完全一样的记录只更新时间戳，不会重复堆积。

## 依赖

`requests`、`pillow`、`numpy` —— ComfyUI 自带环境里都有，一般不用额外装。

## 安装

```bash
git clone https://github.com/siteoj/ComfyUI-H3-PromptWriter.git
```

克隆到 `ComfyUI/custom_nodes/` 下，重启 ComfyUI 即可。依赖 ComfyUI 自带环境都有，
一般不用装；真缺了就 `pip install -r requirements.txt`。

## 许可

节点代码采用 MIT 协议，见 [LICENSE](LICENSE)。

`references/` 下的三份文档**不在此协议范围内**：它们原样取自
[MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3) 的 `skills/h3-prompt-writing/`，
版权归 MiniMax，未作任何改动，详见 [references/README.md](references/README.md)。
