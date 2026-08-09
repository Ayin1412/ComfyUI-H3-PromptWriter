import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// H3 视频提示词撰写 (API) 的前端扩展：
//   1. 左侧 image_N 输入按模式自动增删、自动改名（首帧 / 尾帧 / 参考图 N）
//   2. 把原生的 query / result / action 三个 widget 藏起来，换成一个左右两栏的编辑器，
//      左边写需求、右边放写好的提示词，跟着节点大小自适应
//   3. 工具条：✍️ 生成提示词（只跑这一个节点，不会带着整张图一起跑）、💾 保存、
//      📚 提示词库、🔑 API 设置

const NODE_NAME = "H3PromptWriter";
const IMAGE_RE = /^image_(\d+)$/;
const DEFAULT_SIZE = [780, 470];

// 和后端 modes.py 里的表保持一致
//   count: 该模式固定需要几张图；null = 不限，末尾自动留一个空槽
const MODE_SPEC = {
    T2VA: { count: 0, slots: [] },
    I2VA: { count: 1, slots: ["首帧 <Picture 1>"] },
    FL2VA: { count: 2, slots: ["首帧 <Picture 1>", "尾帧 <Picture 2>"] },
    L2VA: { count: 1, slots: ["尾帧 <Picture 1>"] },
    Ref2VA: { count: null, slots: null },
};

// API 设置面板里的字段，和后端 config.py 的 _SCHEMA 对应
const SETTING_FIELDS = [
    { key: "base_url", label: "接口地址 base_url", type: "text", ph: "https://api.openai.com/v1" },
    { key: "model", label: "模型（接图的模式要选支持视觉的）", type: "text", ph: "gpt-4o" },
    { key: "api_key", label: "API Key（右边的眼睛切换显示）", type: "password", ph: "sk-…" },
    { key: "temperature", label: "temperature", type: "number", step: "0.05", min: 0, max: 2 },
    { key: "max_tokens", label: "max_tokens", type: "number", step: "256", min: 256, max: 32768 },
    { key: "timeout", label: "单次超时（秒）", type: "number", step: "10", min: 10, max: 900 },
    { key: "retries", label: "失败重试次数", type: "number", step: "1", min: 0, max: 5 },
    { key: "max_image_side", label: "发图前缩到最长边", type: "number", step: "64", min: 256, max: 2048 },
    { key: "image_detail", label: "图片细节档位", type: "select", options: ["auto", "low", "high"] },
    { key: "extra_requirements", label: "额外约束（每次生成都会附加）", type: "text",
      ph: "例如：只用一个镜头 / 不要台词" },
];

/* ------------------------------------------------------------------ 接口 */

async function apiCall(path, body) {
    const res = await api.fetchApi(`/h3_prompt/${path}`, body === undefined ? undefined : {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    let data = {};
    try {
        data = await res.json();
    } catch (e) {
        /* 忽略空响应体 */
    }
    if (!res.ok) throw new Error(data.error || `请求失败 (${res.status})`);
    return data;
}

const listPrompts = () => apiCall("prompts").then((d) => d.items || []);
const savePrompt = (payload) => apiCall("save", payload);
const updatePrompt = (patch) => apiCall("update", patch).then((d) => d.item);
const deletePrompt = (id) => apiCall("delete", { id });
const getConfig = () => apiCall("config");
const setConfig = (patch) => apiCall("config", patch);
const fetchModels = (conn) => apiCall("models", conn).then((d) => d.items || []);
const testConnection = (conn) => apiCall("test", conn);
const generateDirect = (payload) => apiCall("generate", payload).then((d) => d.prompt || "");

/* ------------------------------------------------------------ 节点小工具 */

const getWidget = (node, name) => (node.widgets || []).find((w) => w.name === name);

function widgetValue(node, name) {
    const w = getWidget(node, name);
    return w ? String(w.value ?? "") : "";
}

function setWidgetValue(node, name, value) {
    const w = getWidget(node, name);
    if (!w) return;
    w.value = value;
    if (w.callback) w.callback(value);
}

// 编辑器装上了就走它的方法，装不上（前端版本对不上，退回原生文本框）也不能崩
function setText(node, name, value) {
    if (node.h3SetText) node.h3SetText(name, value);
    else {
        setWidgetValue(node, name, value);
        node.setDirtyCanvas(true, true);
    }
}

function setBusy(node, busy) {
    node.h3Busy = busy;
    node.h3SetBusy?.(busy);
}

function modeCode(node) {
    const code = widgetValue(node, "mode").trim().split(/\s+/)[0];
    return MODE_SPEC[code] ? code : "T2VA";
}

function toast(msg, severity = "success") {
    if (app.extensionManager?.toast?.add) {
        app.extensionManager.toast.add({ severity, summary: msg, life: 3000 });
    } else {
        console.log(`[H3] ${msg}`);
    }
}

/* ------------------------------------------------------------ 图片输入槽 */

const inputIndex = (node, name) => (node.inputs || []).findIndex((i) => i.name === name);

function imageNumbers(node) {
    const nums = [];
    for (const inp of node.inputs || []) {
        const m = IMAGE_RE.exec(inp.name);
        if (m) nums.push(parseInt(m[1], 10));
    }
    return nums.sort((a, b) => a - b);
}

const slotEmpty = (node, n) => {
    const idx = inputIndex(node, `image_${n}`);
    return idx < 0 || node.inputs[idx].link == null;
};

function removeSlot(node, n) {
    const idx = inputIndex(node, `image_${n}`);
    if (idx < 0) return;
    if (node.inputs[idx].link != null) node.disconnectInput(idx);
    node.removeInput(idx);
}

function labelSlots(node, code) {
    const spec = MODE_SPEC[code];
    for (const inp of node.inputs || []) {
        const m = IMAGE_RE.exec(inp.name);
        if (!m) continue;
        const n = parseInt(m[1], 10);
        if (!spec.slots) inp.label = `参考图 <Picture ${n}>`;
        else inp.label = spec.slots[n - 1] || `⚠ 多余的图 ${n}（${code} 用不到）`;
    }
}

// 保证 image_N 的数量符合当前模式：固定张数的模式补齐到刚好几个；
// Ref2VA 则始终在末尾留恰好一个空槽，接满了自动长出下一个。
//
// force = 用户主动换了模式，多出来的槽即使连着线也拆掉；否则只收空槽，
// 免得工作流加载途中的时序问题把已经连好的图给弄丢了。
function syncImageSlots(node, force = false) {
    const code = modeCode(node);
    const spec = MODE_SPEC[code];

    if (spec.count !== null) {
        for (const n of imageNumbers(node)) {
            if (n > spec.count && (force || slotEmpty(node, n))) removeSlot(node, n);
        }
        for (let n = 1; n <= spec.count; n++) {
            if (inputIndex(node, `image_${n}`) < 0) node.addInput(`image_${n}`, "IMAGE");
        }
    } else {
        if (imageNumbers(node).length === 0) node.addInput("image_1", "IMAGE");

        // 末尾连续的空槽收掉，只留一个
        for (;;) {
            const nums = imageNumbers(node);
            if (nums.length <= 1) break;
            const last = nums[nums.length - 1];
            const prev = nums[nums.length - 2];
            if (slotEmpty(node, last) && slotEmpty(node, prev)) removeSlot(node, last);
            else break;
        }

        const nums = imageNumbers(node);
        const last = nums[nums.length - 1];
        if (!slotEmpty(node, last)) node.addInput(`image_${last + 1}`, "IMAGE");
    }

    labelSlots(node, code);
    node.setDirtyCanvas(true, true);
}

/* ------------------------------------------------------------------ 样式 */

const CSS = `
/* ---- 节点上的两栏编辑器 ---- */
.h3-editor{display:flex;flex-direction:column;gap:6px;width:100%;height:100%;
  box-sizing:border-box;font-family:sans-serif;color:var(--fg-color,#fff);overflow:hidden;}
.h3-toolbar{display:flex;gap:6px;align-items:center;flex-wrap:wrap;flex:0 0 auto;}
.h3-toolbar .h3-grow{flex:1;}
.h3-cols{display:flex;gap:8px;flex:1 1 auto;min-height:0;}
.h3-col{display:flex;flex-direction:column;gap:3px;min-width:0;min-height:0;}
.h3-col-q{flex:4 1 0;}
.h3-col-r{flex:6 1 0;}
.h3-col-head{display:flex;align-items:baseline;gap:6px;font-size:11px;opacity:.7;flex:0 0 auto;}
.h3-col-head b{font-weight:600;opacity:.95;}
.h3-editor textarea{flex:1 1 auto;min-height:0;width:100%;box-sizing:border-box;resize:none;
  background:var(--comfy-input-bg,#222);color:var(--input-text,#ddd);
  border:1px solid var(--border-color,#4e4e4e);border-radius:4px;padding:6px 7px;
  font-family:inherit;font-size:12px;line-height:1.5;outline:none;overflow:hidden auto;}
.h3-editor textarea:focus{border-color:#6a9;}

/* ---- 按钮 ---- */
.h3-btn{background:var(--comfy-input-bg,#222);color:var(--fg-color,#fff);
  border:1px solid var(--border-color,#4e4e4e);border-radius:4px;padding:5px 10px;
  cursor:pointer;font-size:12px;white-space:nowrap;font-family:inherit;}
.h3-btn:hover:not(:disabled){background:#4a4a4a;}
.h3-btn:disabled{opacity:.55;cursor:default;}
.h3-btn.h3-primary{background:#3d6a4d;border-color:#4e8a63;}
.h3-btn.h3-primary:hover:not(:disabled){background:#4a8060;}
.h3-btn.h3-danger:hover:not(:disabled){background:#7a3535;border-color:#a04a4a;}

/* ---- 弹窗 ---- */
.h3-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;
  display:flex;align-items:center;justify-content:center;font-family:sans-serif;}
.h3-dialog{background:var(--comfy-menu-bg,#353535);color:var(--fg-color,#fff);
  border:1px solid var(--border-color,#4e4e4e);border-radius:8px;
  width:min(960px,92vw);height:min(640px,88vh);display:flex;flex-direction:column;
  box-shadow:0 8px 32px rgba(0,0,0,.5);font-size:13px;}
.h3-header{display:flex;align-items:center;gap:8px;padding:10px 12px;
  border-bottom:1px solid var(--border-color,#4e4e4e);}
.h3-title{font-weight:bold;font-size:14px;white-space:nowrap;}
.h3-header .h3-search{flex:1;min-width:80px;}
.h3-dialog input,.h3-dialog textarea,.h3-dialog select{background:var(--comfy-input-bg,#222);
  color:var(--input-text,#ddd);border:1px solid var(--border-color,#4e4e4e);
  border-radius:4px;padding:5px 7px;font-family:inherit;font-size:12px;outline:none;}
.h3-dialog input:focus,.h3-dialog textarea:focus{border-color:#6a9;}
.h3-body{flex:1;display:flex;min-height:0;}
.h3-list{width:36%;min-width:220px;overflow-y:auto;border-right:1px solid var(--border-color,#4e4e4e);}
.h3-item{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.06);cursor:pointer;}
.h3-item:hover{background:rgba(255,255,255,.06);}
.h3-item.h3-active{background:rgba(110,170,140,.22);}
.h3-item-name{font-weight:bold;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.h3-item-meta{font-size:11px;opacity:.55;margin-top:2px;}
.h3-item-preview{font-size:11px;opacity:.75;margin-top:3px;max-height:2.6em;overflow:hidden;
  word-break:break-all;}
.h3-tag{display:inline-block;padding:0 5px;border-radius:3px;background:rgba(110,170,140,.28);
  font-size:10px;margin-right:4px;}
.h3-empty{padding:20px 12px;opacity:.6;text-align:center;}
.h3-detail{flex:1;display:flex;flex-direction:column;padding:10px;gap:8px;min-width:0;}
.h3-detail-head{display:flex;gap:8px;}
.h3-detail-head .h3-name{flex:2;min-width:0;}
.h3-detail-head .h3-tags{flex:1;min-width:0;}
.h3-text{flex:1;resize:none;line-height:1.5;white-space:pre-wrap;}
.h3-detail-actions{display:flex;gap:8px;justify-content:flex-end;}
.h3-footer{display:flex;align-items:center;gap:8px;padding:10px 12px;
  border-top:1px solid var(--border-color,#4e4e4e);}
.h3-hint{flex:1;font-size:11px;opacity:.65;}
.h3-small{width:min(520px,92vw);height:auto;max-height:88vh;}
.h3-form{padding:14px;display:flex;flex-direction:column;gap:9px;overflow-y:auto;}
.h3-form label{display:flex;flex-direction:column;gap:4px;font-size:12px;opacity:.85;}
.h3-form input,.h3-form select{width:100%;box-sizing:border-box;}
.h3-row{display:flex;gap:6px;align-items:center;}
.h3-row input,.h3-row select{flex:1;min-width:0;}
.h3-row .h3-btn{flex:0 0 auto;}
.h3-icon{padding:4px 8px;line-height:1.2;}
.h3-note{font-size:11px;opacity:.6;line-height:1.6;}
.h3-result{font-size:12px;line-height:1.5;min-height:1.2em;word-break:break-all;}
.h3-result.h3-good{color:#7ad39a;}
.h3-result.h3-bad{color:#e08a8a;}
`;

function injectCSS() {
    if (document.getElementById("h3-styles")) return;
    const style = document.createElement("style");
    style.id = "h3-styles";
    style.textContent = CSS;
    document.head.appendChild(style);
}

// 输入框里的按键不能冒泡给画布，否则 Delete / 空格之类会误触发 ComfyUI 快捷键。
function isolateKeys(el) {
    for (const type of ["keydown", "keyup", "keypress"]) {
        el.addEventListener(type, (e) => e.stopPropagation());
    }
}

/** 单行输入弹窗（Electron 下 window.prompt 不可用，自己实现一个）。 */
function askText(title, defaultValue = "") {
    injectCSS();
    return new Promise((resolve) => {
        const overlay = document.createElement("div");
        overlay.className = "h3-overlay";
        overlay.innerHTML = `
          <div class="h3-dialog h3-small">
            <div class="h3-header"><span class="h3-title"></span></div>
            <div class="h3-form">
              <input class="h3-ask-input" type="text">
              <div class="h3-detail-actions">
                <button class="h3-btn h3-cancel">取消</button>
                <button class="h3-btn h3-primary h3-ok">确定</button>
              </div>
            </div>
          </div>`;
        overlay.querySelector(".h3-title").textContent = title;
        const input = overlay.querySelector(".h3-ask-input");
        input.value = defaultValue;

        const close = (value) => {
            overlay.remove();
            resolve(value);
        };
        overlay.querySelector(".h3-ok").onclick = () => close(input.value);
        overlay.querySelector(".h3-cancel").onclick = () => close(null);
        overlay.onclick = (e) => {
            if (e.target === overlay) close(null);
        };
        isolateKeys(overlay);
        input.addEventListener("keydown", (e) => {
            if (e.key === "Enter") close(input.value);
            else if (e.key === "Escape") close(null);
        });

        document.body.appendChild(overlay);
        input.focus();
        input.select();
    });
}

/* ------------------------------------------------------------ API 设置弹窗 */

async function openSettings() {
    injectCSS();
    let current = {};
    try {
        current = await getConfig();
    } catch (e) {
        toast(`读取设置失败：${e.message}`, "error");
    }

    const overlay = document.createElement("div");
    overlay.className = "h3-overlay";
    overlay.innerHTML = `
      <div class="h3-dialog h3-small">
        <div class="h3-header"><span class="h3-title">🔑 API 设置</span></div>
        <div class="h3-form">
          <div class="h3-fields"></div>
          <div class="h3-result"></div>
          <div class="h3-note"></div>
          <div class="h3-detail-actions">
            <button class="h3-btn h3-test">🔌 测试连接</button>
            <button class="h3-btn h3-cancel">取消</button>
            <button class="h3-btn h3-primary h3-ok">保存</button>
          </div>
        </div>
      </div>`;

    const $ = (sel) => overlay.querySelector(sel);
    const fields = $(".h3-fields");
    const resultEl = $(".h3-result");
    const inputs = {};

    const say = (msg, kind = "") => {
        resultEl.textContent = msg;
        resultEl.className = "h3-result" + (kind ? ` h3-${kind}` : "");
    };

    /** 一行：标签 + 主控件（+ 右边跟着的小按钮）。 */
    function addField(f, el, ...extras) {
        const label = document.createElement("label");
        label.appendChild(document.createTextNode(f.label));
        if (extras.length) {
            const row = document.createElement("div");
            row.className = "h3-row";
            row.append(el, ...extras);
            label.appendChild(row);
        } else {
            label.appendChild(el);
        }
        inputs[f.key] = el;
        fields.appendChild(label);
        return label;
    }

    for (const f of SETTING_FIELDS) {
        if (f.type === "select") {
            const el = document.createElement("select");
            for (const opt of f.options) {
                const o = document.createElement("option");
                o.value = o.textContent = opt;
                el.appendChild(o);
            }
            el.value = current[f.key] ?? f.options[0];
            addField(f, el);
            continue;
        }

        const el = document.createElement("input");
        el.type = f.type;
        if (f.ph) el.placeholder = f.ph;
        if (f.step) el.step = f.step;
        if (f.min !== undefined) el.min = f.min;
        if (f.max !== undefined) el.max = f.max;
        el.value = current[f.key] ?? "";

        if (f.key === "api_key") {
            // 睁闭眼：切明文 / 圆点
            const eye = document.createElement("button");
            eye.className = "h3-btn h3-icon";
            eye.type = "button";
            eye.title = "显示 / 隐藏";
            eye.textContent = "👁";
            eye.onclick = () => {
                const shown = el.type === "text";
                el.type = shown ? "password" : "text";
                eye.textContent = shown ? "👁" : "🙈";
            };
            addField(f, el, eye);
        } else if (f.key === "model") {
            const pick = document.createElement("select");
            pick.style.display = "none";
            pick.onchange = () => {
                if (pick.value) el.value = pick.value;
            };
            const btn = document.createElement("button");
            btn.className = "h3-btn";
            btn.type = "button";
            btn.textContent = "获取模型";
            btn.onclick = async () => {
                btn.disabled = true;
                btn.textContent = "读取中…";
                say("");
                try {
                    const items = await fetchModels(conn());
                    pick.innerHTML = "";
                    const head = document.createElement("option");
                    head.value = "";
                    head.textContent = `— 共 ${items.length} 个，选一个 —`;
                    pick.appendChild(head);
                    for (const id of items) {
                        const o = document.createElement("option");
                        o.value = o.textContent = id;
                        pick.appendChild(o);
                    }
                    pick.value = items.includes(el.value) ? el.value : "";
                    pick.style.display = items.length ? "" : "none";
                    say(items.length ? `拿到 ${items.length} 个模型` : "接口没返回模型",
                        items.length ? "good" : "bad");
                } catch (e) {
                    say(`获取模型失败：${e.message}`, "bad");
                } finally {
                    btn.disabled = false;
                    btn.textContent = "获取模型";
                }
            };
            const label = addField(f, el, btn);
            label.appendChild(pick);
        } else {
            addField(f, el);
        }
    }

    // 面板上当前填的连接参数（还没保存也能拿来测）
    const conn = () => ({
        base_url: inputs.base_url.value,
        api_key: inputs.api_key.value,
        model: inputs.model.value,
        timeout: Number(inputs.timeout.value) || 60,
    });

    $(".h3-note").textContent =
        `保存在 ${current.path || "user/default/h3_prompt_writer/config.json"}，不会写进工作流文件。`
        + (current.from_env ? "当前的 Key 来自环境变量，保存后会以这里填的为准。" : "")
        + "Key 清空再保存即可删掉。";

    const close = () => overlay.remove();
    $(".h3-cancel").onclick = close;
    overlay.onclick = (e) => {
        if (e.target === overlay) close();
    };
    isolateKeys(overlay);
    overlay.addEventListener("keydown", (e) => {
        if (e.key === "Escape") close();
    });

    $(".h3-test").onclick = async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        say("正在发一句最短的对话…");
        try {
            const d = await testConnection(conn());
            say(`✅ 通了：${d.model} 用时 ${d.ms} ms，回复「${d.reply}」`, "good");
        } catch (err) {
            say(`❌ 不通：${err.message}`, "bad");
        } finally {
            btn.disabled = false;
        }
    };

    $(".h3-ok").onclick = async () => {
        const patch = {};
        for (const f of SETTING_FIELDS) {
            const raw = inputs[f.key].value;
            patch[f.key] = f.type === "number" ? Number(raw) : raw;
        }
        try {
            await setConfig(patch);
            toast("API 设置已保存");
            close();
        } catch (e) {
            say(`保存失败：${e.message}`, "bad");
        }
    };

    document.body.appendChild(overlay);
    inputs.base_url.focus();
}

/* ---------------------------------------------------------- 提示词库面板 */

function fmtDate(ts) {
    const d = new Date((ts || 0) * 1000);
    if (isNaN(d.getTime())) return "";
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const collectMeta = (node) => ({
    mode: modeCode(node),
    query: widgetValue(node, "query").slice(0, 500),
});

async function saveCurrent(node) {
    const text = widgetValue(node, "result");
    if (!text.trim()) return toast("右边的提示词框是空的", "warn");
    const name = await askText("给这条提示词起个名字（留空自动命名）", "");
    if (name === null) return null;
    try {
        const d = await savePrompt({ text, name, ...collectMeta(node) });
        toast(`已存入提示词库：${d.item.name}` + (d.path ? `，并导出 ${d.path}` : ""));
        return d.item;
    } catch (e) {
        alert(`保存失败：${e.message}`);
        return null;
    }
}

function openLibrary(node) {
    injectCSS();

    const overlay = document.createElement("div");
    overlay.className = "h3-overlay";
    overlay.innerHTML = `
      <div class="h3-dialog">
        <div class="h3-header">
          <span class="h3-title">📚 H3 提示词库</span>
          <input class="h3-search" type="text" placeholder="搜索名称 / 模式 / 需求 / 正文…">
          <button class="h3-btn h3-save-current">＋ 存入当前结果</button>
          <button class="h3-btn h3-close">✕</button>
        </div>
        <div class="h3-body">
          <div class="h3-list"></div>
          <div class="h3-detail">
            <div class="h3-detail-head">
              <input class="h3-name" type="text" placeholder="名称（可随时修改，方便查找）">
              <input class="h3-tags" type="text" placeholder="标签，如：产品广告, 单镜头">
            </div>
            <textarea class="h3-text" spellcheck="false" placeholder="选中左侧的一条后可在这里编辑"></textarea>
            <div class="h3-detail-actions">
              <button class="h3-btn h3-danger h3-delete">删除</button>
              <button class="h3-btn h3-copy">复制</button>
              <button class="h3-btn h3-primary h3-apply">保存修改</button>
            </div>
          </div>
        </div>
        <div class="h3-footer">
          <span class="h3-hint"></span>
          <button class="h3-btn h3-primary h3-load">载入到节点</button>
        </div>
      </div>`;

    const $ = (sel) => overlay.querySelector(sel);
    const listEl = $(".h3-list");
    const searchEl = $(".h3-search");
    const nameEl = $(".h3-name");
    const tagsEl = $(".h3-tags");
    const textEl = $(".h3-text");
    const hintEl = $(".h3-hint");

    let items = [];
    let selectedId = null;

    const selected = () => items.find((i) => i.id === selectedId) || null;
    const hint = (msg) => {
        hintEl.textContent = msg;
    };

    function renderDetail() {
        const item = selected();
        nameEl.value = item ? item.name : "";
        tagsEl.value = item ? item.tags || "" : "";
        textEl.value = item ? item.text : "";
        const disabled = !item;
        for (const sel of [".h3-apply", ".h3-delete", ".h3-load", ".h3-copy"]) {
            $(sel).disabled = disabled;
        }
        nameEl.disabled = tagsEl.disabled = textEl.disabled = disabled;
    }

    function renderList() {
        const q = searchEl.value.trim().toLowerCase();
        const shown = q
            ? items.filter((i) =>
                  `${i.name}\n${i.tags || ""}\n${i.mode || ""}\n${i.query || ""}\n${i.text}`
                      .toLowerCase()
                      .includes(q))
            : items;

        listEl.innerHTML = "";
        if (!shown.length) {
            const empty = document.createElement("div");
            empty.className = "h3-empty";
            empty.textContent = items.length ? "没有匹配的提示词" : "提示词库还是空的";
            listEl.appendChild(empty);
            return;
        }

        for (const item of shown) {
            const row = document.createElement("div");
            row.className = "h3-item" + (item.id === selectedId ? " h3-active" : "");

            const name = document.createElement("div");
            name.className = "h3-item-name";
            if (item.mode) {
                const tag = document.createElement("span");
                tag.className = "h3-tag";
                tag.textContent = item.mode;
                name.appendChild(tag);
            }
            name.appendChild(document.createTextNode(item.name));

            const meta = document.createElement("div");
            meta.className = "h3-item-meta";
            meta.textContent = fmtDate(item.updated)
                + (item.model ? ` · ${item.model}` : "")
                + (item.tags ? ` · ${item.tags}` : "");

            const preview = document.createElement("div");
            preview.className = "h3-item-preview";
            preview.textContent = (item.query || item.text).replace(/\s+/g, " ").slice(0, 120);

            row.append(name, meta, preview);
            row.onclick = () => {
                selectedId = item.id;
                renderList();
                renderDetail();
            };
            listEl.appendChild(row);
        }
    }

    async function reload(keepId = selectedId) {
        try {
            items = await listPrompts();
        } catch (e) {
            hint(`读取失败：${e.message}`);
            items = [];
        }
        selectedId = items.some((i) => i.id === keepId) ? keepId : (items[0]?.id ?? null);
        renderList();
        renderDetail();
    }

    const close = () => overlay.remove();
    $(".h3-close").onclick = close;
    overlay.onclick = (e) => {
        if (e.target === overlay) close();
    };
    isolateKeys(overlay);
    overlay.addEventListener("keydown", (e) => {
        if (e.key === "Escape") close();
    });

    searchEl.oninput = renderList;

    $(".h3-save-current").onclick = async () => {
        const item = await saveCurrent(node);
        if (item) await reload(item.id);
    };

    $(".h3-apply").onclick = async () => {
        const item = selected();
        if (!item) return;
        try {
            const updated = await updatePrompt({
                id: item.id, name: nameEl.value, tags: tagsEl.value, text: textEl.value,
            });
            hint(`已更新：${updated.name}`);
            await reload(updated.id);
        } catch (e) {
            hint(`更新失败：${e.message}`);
        }
    };

    $(".h3-delete").onclick = async () => {
        const item = selected();
        if (!item) return;
        if (!confirm(`确定删除「${item.name}」？`)) return;
        try {
            await deletePrompt(item.id);
            hint("已删除");
            await reload(null);
        } catch (e) {
            hint(`删除失败：${e.message}`);
        }
    };

    $(".h3-copy").onclick = async () => {
        try {
            await navigator.clipboard.writeText(textEl.value);
            hint("已复制到剪贴板");
        } catch (e) {
            textEl.select();
            hint("复制失败，已全选，按 Ctrl+C");
        }
    };

    $(".h3-load").onclick = () => {
        if (!selected()) return;
        setText(node, "result", textEl.value);
        if (selected().query) setText(node, "query", selected().query);
        hint("已载入节点");
        toast("已载入到节点");
        close();
    };

    document.body.appendChild(overlay);
    renderDetail();
    reload().then(() => searchEl.focus());
}

/* ---------------------------------------------------- 图片引用（不排队用） */

const IMG_EXT_RE = /\.(png|jpe?g|webp|bmp|gif|tiff?)(\s*\[|$)/i;

/** 从 /view?filename=…&subfolder=…&type=… 这样的地址里抠出引用。 */
function refFromUrl(src) {
    try {
        const q = new URL(src, window.location.origin).searchParams;
        const filename = q.get("filename");
        if (!filename) return null;
        return { filename, subfolder: q.get("subfolder") || "", type: q.get("type") || "output" };
    } catch (e) {
        return null;
    }
}

/** 从 /history 里取各节点最近一次跑出来的图片：节点 id → [{filename, subfolder, type}]。
 *
 * 新前端（1.4x）不再把执行结果挂在节点对象上，所以要问后端。只有输出节点会在 history
 * 里留下 outputs，PreviewBridge 这类「既是输出节点又有输出槽」的节点因此也能直接用。
 */
async function recentOutputImages() {
    const map = {};
    try {
        const r = await api.fetchApi("/history?max_items=64");
        const hist = await r.json();
        // 对象键序即插入序，后面的更新，正好让最近一次执行覆盖旧的
        for (const entry of Object.values(hist || {})) {
            const graph = entry?.prompt?.[2] || {};
            for (const [nodeId, out] of Object.entries(entry?.outputs || {})) {
                const imgs = (out?.images || []).filter((i) => i && i.filename);
                if (!imgs.length) continue;
                map[String(nodeId)] = {
                    // 节点 id 会跨工作流复用，光看 id 会张冠李戴，把类型一起记下来校验
                    classType: graph[nodeId]?.class_type,
                    refs: imgs.map((i) => ({
                        filename: i.filename, subfolder: i.subfolder || "", type: i.type || "temp",
                    })),
                };
            }
        }
    } catch (e) {
        console.warn("[H3] 读 /history 失败，只能靠文件名 widget 找图", e);
    }
    return map;
}

/** 某个节点身上能直接拿到的图片引用。 */
function refsOfNode(node, history) {
    // 1. 老前端把预览图挂在节点上
    const imgs = node?.imgs || node?.images;
    if (Array.isArray(imgs) && imgs.length) {
        const refs = imgs.map((im) => refFromUrl(im?.src || im?.url || im)).filter(Boolean);
        if (refs.length) return refs;
    }
    // 2. LoadImage 这类的文件名 widget —— 它才是这个节点接下来真正会读的文件
    //    （"example.png [input]" 的标注后端会自己处理）
    for (const w of node?.widgets || []) {
        const v = w?.value;
        if (typeof v === "string" && IMG_EXT_RE.test(v)) {
            return [{ filename: v, subfolder: "", type: "input" }];
        }
    }
    // 3. 兜底：这个节点最近一次执行留下的输出，类型对得上才认
    const hit = history?.[String(node?.id)];
    if (hit?.refs?.length && hit.classType === node?.type) return hit.refs;
    return null;
}

/** 顺着 IMAGE 连线往上找最近一个能拿到图的节点。找不到返回 null。 */
function resolveUpstreamRefs(node, history, depth = 0) {
    if (!node || depth > 8) return null;
    const own = refsOfNode(node, history);
    if (own) return { refs: own, from: node, hops: depth };

    for (const inp of node.inputs || []) {
        if (inp.type !== "IMAGE" || inp.link == null) continue;
        const link = app.graph.links[inp.link];
        const up = link && app.graph.getNodeById(link.origin_id);
        const found = resolveUpstreamRefs(up, history, depth + 1);
        if (found) return found;
    }
    return null;
}

/** 本节点所有 image_N 输入 → 图片引用列表。任何一个解析不出就返回 refs: null。 */
async function collectImageRefs(node) {
    const slots = (node.inputs || [])
        .map((inp) => ({ inp, m: IMAGE_RE.exec(inp.name) }))
        .filter((s) => s.m && s.inp.link != null)
        .sort((a, b) => parseInt(a.m[1], 10) - parseInt(b.m[1], 10));

    if (!slots.length) return { refs: [], notes: [] }; // T2VA

    const history = await recentOutputImages();
    const refs = [];
    const notes = [];
    for (const s of slots) {
        const link = app.graph.links[s.inp.link];
        const src = link && app.graph.getNodeById(link.origin_id);
        const found = resolveUpstreamRefs(src, history);
        const name = s.inp.label || s.inp.name;
        if (!found) {
            return { refs: null, why: `${name} 上游的「${src?.title || "?"}」还没有落到磁盘的图` };
        }
        if (found.hops > 0) notes.push(`${name} 取的是上游「${found.from.title}」的图`);
        refs.push(...found.refs);
    }
    return { refs, notes };
}

/* -------------------------------------------------------- 生成（单节点跑） */

/** 轮询 /history，等这次任务跑完，拿到写好的提示词或者错误信息。 */
function waitForResult(promptId, nodeId) {
    return new Promise((resolve) => {
        let tries = 0;
        const tick = async () => {
            tries++;
            try {
                const r = await api.fetchApi(`/history/${promptId}`);
                const entry = (await r.json())?.[promptId];
                if (entry) {
                    const out = entry.outputs?.[nodeId]?.h3_prompt;
                    if (Array.isArray(out) && out.length) return resolve({ text: out.join("") });
                    if (entry.status?.status_str === "error" || entry.status?.completed) {
                        // 错误信息藏在 status.messages 里，形如 ["execution_error", {...}]
                        for (const [event, data] of entry.status?.messages || []) {
                            if (event === "execution_error") {
                                return resolve({
                                    error: data?.exception_message || data?.exception_type || "执行失败",
                                });
                            }
                        }
                        return resolve(entry.status?.completed ? {} : { error: "执行失败" });
                    }
                }
            } catch (e) {
                /* 继续轮询 */
            }
            if (tries > 1800) return resolve({ error: "等待超时" }); // ~15 分钟上限
            setTimeout(tick, 500);
        };
        tick();
    });
}

async function generate(node) {
    if (node.h3Busy) return;
    if (!widgetValue(node, "query").trim()) {
        toast("先在左边写清楚你想要什么样的视频", "warn");
        return;
    }

    setBusy(node, true);
    try {
        // 首选：完全不碰执行队列。前端把图片解析成 {filename, subfolder, type}，
        // 交给 /h3_prompt/generate 直接干活——正在出视频时也能立刻用。
        const { refs, notes, why } = await collectImageRefs(node);
        if (refs) {
            if (notes.length) toast(notes.join("；"), "info");
            const text = await generateDirect({
                mode: widgetValue(node, "mode"),
                query: widgetValue(node, "query"),
                duration: Number(widgetValue(node, "duration_seconds")) || 6,
                images: refs,
            });
            setText(node, "result", text);
            return;
        }
        // 兜底：图还只存在于显存里，只能让 ComfyUI 把它算出来，这一次要排队
        toast(`${why}，这次改走执行队列（会排在当前任务后面）。想每次都免排队，接个 LoadImage。`,
              "warn");
        await generateViaQueue(node);
    } catch (e) {
        console.error("[H3] 生成失败", e);
        toast(`生成失败：${e.message}`, "error");
    } finally {
        setBusy(node, false);
    }
}

/** 兜底路径：提交整张图，但用 partial_execution_targets 限定只跑本节点和上游图片节点。 */
async function generateViaQueue(node) {
    const full = await app.graphToPrompt();
    const prompt = full.output;
    const id = String(node.id);
    if (!prompt[id]) throw new Error("节点不在要执行的图里（是不是被 Bypass / Mute 了？）");
    prompt[id].inputs.action = "generate";

    const r = await api.fetchApi("/prompt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            prompt,
            client_id: api.clientId,
            partial_execution_targets: [id],
            extra_data: { extra_pnginfo: { workflow: full.workflow } },
        }),
    });
    if (!r.ok) {
        let detail = "";
        try {
            const j = await r.json();
            detail = j?.error?.message || j?.error?.type || "";
            console.error("[H3] /prompt 被拒绝", j);
        } catch (e) {
            /* 响应体不是 json */
        }
        throw new Error(detail || `提交失败 (${r.status})`);
    }

    const { prompt_id } = await r.json();
    const res = await waitForResult(prompt_id, id);
    if (res.error) toast(res.error, "error");
    else if (res.text) setText(node, "result", res.text); // onExecuted 一般已经填过了，这里兜底
    else toast("没拿到结果，看看控制台", "warn");
}

/* -------------------------------------------------------- 两栏编辑器 widget */

function buildEditor(node) {
    injectCSS();

    const root = document.createElement("div");
    root.className = "h3-editor";
    root.innerHTML = `
      <div class="h3-toolbar">
        <button class="h3-btn h3-primary h3-gen">✍️ 生成提示词</button>
        <span class="h3-grow"></span>
        <button class="h3-btn h3-save">💾 保存</button>
        <button class="h3-btn h3-lib">📚 提示词库</button>
        <button class="h3-btn h3-cfg">🔑 API 设置</button>
      </div>
      <div class="h3-cols">
        <div class="h3-col h3-col-q">
          <div class="h3-col-head"><b>需求 query</b><span>你想要什么样的视频</span></div>
          <textarea class="h3-ta-query" spellcheck="false"
            placeholder="用大白话写：内容、动作、镜头、台词、氛围、音效…"></textarea>
        </div>
        <div class="h3-col h3-col-r">
          <div class="h3-col-head"><b>提示词 prompt</b><span>写好的结果，可直接手改，节点输出的就是它</span></div>
          <textarea class="h3-ta-result" spellcheck="false"
            placeholder="点左上角「✍️ 生成提示词」，写好的 H3 提示词会出现在这里"></textarea>
        </div>
      </div>`;

    const $ = (sel) => root.querySelector(sel);
    const areas = { query: $(".h3-ta-query"), result: $(".h3-ta-result") };
    const genBtn = $(".h3-gen");

    for (const [name, ta] of Object.entries(areas)) {
        isolateKeys(ta);
        ta.value = widgetValue(node, name);
        ta.addEventListener("input", () => setWidgetValue(node, name, ta.value));
    }

    genBtn.onclick = () => generate(node);
    $(".h3-save").onclick = () => saveCurrent(node);
    $(".h3-lib").onclick = () => openLibrary(node);
    $(".h3-cfg").onclick = () => openSettings();

    // 从 widget 值刷新到文本框（载入工作流、执行完回填、从库里载入都会用到）
    node.h3Refresh = () => {
        for (const [name, ta] of Object.entries(areas)) {
            const v = widgetValue(node, name);
            if (ta.value !== v) ta.value = v;
        }
    };
    node.h3SetText = (name, value) => {
        setWidgetValue(node, name, value);
        node.h3Refresh();
        node.setDirtyCanvas(true, true);
    };
    node.h3SetBusy = (busy) => {
        genBtn.disabled = busy;
        genBtn.textContent = busy ? "⏳ 生成中…" : "✍️ 生成提示词";
    };

    return root;
}

/** 原生 query / result / action 三个 widget 藏起来，只留它们的值用于序列化。 */
function hideNativeWidgets(node) {
    for (const name of ["query", "result", "action"]) {
        const w = getWidget(node, name);
        if (!w) continue;
        w.hidden = true; // 新前端的布局会跳过 hidden 的 widget
        const el = w.element || w.inputEl;
        if (el?.style) el.style.display = "none";
    }
}

function unhideNativeWidgets(node) {
    for (const name of ["query", "result"]) {
        const w = getWidget(node, name);
        if (!w) continue;
        w.hidden = false;
        const el = w.element || w.inputEl;
        if (el?.style) el.style.display = "";
    }
}

function installEditor(node) {
    if (typeof node.addDOMWidget !== "function") return false;
    try {
        hideNativeWidgets(node);
        const el = buildEditor(node);
        const w = node.addDOMWidget("h3_editor", "h3editor", el, {
            serialize: false,
            hideOnZoom: false,
            getMinHeight: () => 200,
            getMaxHeight: () => 100000, // 尽量吃掉节点剩下的高度
        });
        // 它不是后端的输入，别混进提交的 prompt 里
        if (w) {
            w.serialize = false;
            if (w.options) w.options.serialize = false;
        }
        return true;
    } catch (e) {
        // 前端版本对不上时退回原生的上下两个文本框，至少节点还能用
        console.error("[H3] 两栏编辑器初始化失败，退回默认布局", e);
        unhideNativeWidgets(node);
        return false;
    }
}

/* ------------------------------------------------------------------ 注册 */

app.registerExtension({
    name: "minimax.h3.prompt.writer",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;

            // 换模式要重新排图片输入
            const modeWidget = getWidget(this, "mode");
            if (modeWidget) {
                const prev = modeWidget.callback;
                modeWidget.callback = (...args) => {
                    const out = prev ? prev.apply(modeWidget, args) : undefined;
                    syncImageSlots(this, true); // 主动换模式，多余的槽连着线也拆掉
                    return out;
                };
            }

            installEditor(this);
            syncImageSlots(this);
            const size = [
                Math.max(DEFAULT_SIZE[0], this.size?.[0] || 0),
                Math.max(DEFAULT_SIZE[1], this.size?.[1] || 0),
            ];
            if (this.setSize) this.setSize(size);
            else this.size = size;
            return r;
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (slotType) {
            const r = onConnectionsChange ? onConnectionsChange.apply(this, arguments) : undefined;
            // 1 = LiteGraph.INPUT；加载工作流的过程中不要动槽位
            if (slotType === 1 && !this.h3Configuring) syncImageSlots(this);
            return r;
        };

        // 载入已保存的工作流后，把槽位补回来、文本框内容同步过来
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            let r;
            this.h3Configuring = true;
            try {
                r = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            } finally {
                this.h3Configuring = false;
            }
            hideNativeWidgets(this);
            syncImageSlots(this);
            this.h3Refresh?.();
            // 存盘的一定是 passthrough，别让上次的 generate 状态留下来
            setWidgetValue(this, "action", "passthrough");
            return r;
        };

        // 跑完把写好的提示词回填到右边的框
        const onExecuted = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            const r = onExecuted ? onExecuted.apply(this, arguments) : undefined;
            const text = message?.h3_prompt;
            if (Array.isArray(text) && text.length) setText(this, "result", text.join(""));
            return r;
        };

        const getExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (_, options) {
            const r = getExtraMenuOptions ? getExtraMenuOptions.apply(this, arguments) : undefined;
            options.unshift(
                { content: "✍️ 生成提示词", callback: () => generate(this) },
                { content: "📚 打开 H3 提示词库", callback: () => openLibrary(this) },
                { content: "🔑 API 设置", callback: () => openSettings() },
            );
            return r;
        };
    },
});
