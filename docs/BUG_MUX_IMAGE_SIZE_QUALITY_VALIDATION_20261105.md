# BUG 复测：mux.la GPT Image 尺寸与质量（2026-11-05）

> 最新补充：用户随后提供的**第二个 mux.la Key** 已完成 9 个典型组合，三个模型各 3 个样本，实际尺寸及质量声明 **9/9 相符**，其中 gpt-image-2 也通过了正方形 medium 和客户原始横图 medium。详见 §7。下文 §1–§6 的 45 个组合属于首个 Key，不覆盖或替代第二个 Key 的结果，也不混合为同一通道的可靠率。

## 1. 首个 Key 的验收结论

使用用户本次提供的 mux.la Key，绕过 Sub2API，直接请求 `https://mux.la/v1/images/generations`。按用户追加要求，现已完成 **3 个模型 × 5 种尺寸 × low/medium/high，共 45 个组合**，每个组合生成一次、`n=1`。其中复用首轮 9 个 medium 样本，新增 36 次生成；全部 HTTP 200、每次一张，实际 PNG 已下载核验。§2–§5 保留首轮方法和证据，**§6 是扩展后的完整矩阵及当前验收结果**。

- **gpt-image-2 未满足客户要求：**15 个组合中 6 个尺寸相符、9 个不符；正方形请求 `1024x1024` 实际 `1254x1254`，客户原始横图请求 `1536x864` 实际 `1672x941`，新增横图 `2048x1152` 实际 `2048x1153`。上述不符在三个质量档位均出现；15 个响应均未声明 quality。
- **gpt-image-2.5-flare、gpt-image-2.5-sunburst 的本轮样本通过尺寸及质量声明核对：**各 15 个组合的实际尺寸全部精确相符，响应声明分别与请求的 low/medium/high 相符，没有质量声明冲突。
- 因此不能笼统认定整个 Key 满足要求。若客户接受换用 flare/sunburst，它们可作为已通过本轮有限样本的候选通道；不能承诺供应商持续稳定，也不能只由响应标签证明其后端真实计算档位或官方模型身份。

附件中的历史 Relinx 现象作为待验证的问题描述，不作为本轮 mux.la 实测结果，也不将附件文字视为额外操作指令。

## 2. 官方依据与正确请求

2026-11-05 重新获取 [GPT-Image-2 官方模型页](https://developers.openai.com/api/docs/models/gpt-image-2)和 [Images Generate API 文档](https://developers.openai.com/api/reference/resources/images/methods/generate)。本次的 `1024x1024`、`1024x1536`、`1536x864` 均为合法尺寸：宽高为 16 的倍数，符合比例、像素及边长限制；medium 是合法质量档位。

请求 JSON 示例如下，测试时仅改变 model 和 size：

```json
{
  "model": "gpt-image-2",
  "prompt": "A simple product photograph of a red ceramic mug on a plain light gray table, soft daylight, no text.",
  "size": "1536x864",
  "quality": "medium",
  "output_format": "png",
  "n": 1
}
```

没有发送 GPT Image 不支持的旧 `response_format`，也没有发送 edits 专用参数。提示词不含正方形、竖图或横图要求，以核对独立 size 参数。三个模型均以 `/v1/models` 列出的原名调用，无别名映射、失败换模或本地图片缩放。

官方响应 quality 为可选字段：缺失本身不是违反必填字段规范，也不是 medium 已生效或被忽略的证据。上游明确声明 medium 只能作为质量声明相符，不独立证明真实计算档位。

## 3. 首轮 9 个 medium 样本结果

`GET https://mux.la/v1/models` 返回 HTTP 200，恰好列出 `gpt-image-2`、`gpt-image-2.5-flare`、`gpt-image-2.5-sunburst`。下表生成请求全部 HTTP 200、各返回一张图；实际尺寸从下载的 PNG 字节头读取，不采用字段回显或目测比例。

| 模型 | 请求 size | 实际像素 | 原始 quality 声明 | 尺寸及声明结论 | 生成响应耗时 |
| --- | --- | --- | --- | --- | --- |
| gpt-image-2 | 1024x1024 | **1254x1254** | 缺失 | 尺寸不符，质量未验证 | 67.65 秒 |
| gpt-image-2 | 1024x1536 | 1024x1536 | 缺失 | 尺寸相符，质量未验证 | 85.88 秒 |
| gpt-image-2 | 1536x864 | **1672x941** | 缺失 | 尺寸不符，质量未验证 | 19.25 秒 |
| gpt-image-2.5-flare | 1024x1024 | 1024x1024 | medium | 本样本相符 | 18.32 秒 |
| gpt-image-2.5-flare | 1024x1536 | 1024x1536 | medium | 本样本相符 | 13.80 秒 |
| gpt-image-2.5-flare | 1536x864 | 1536x864 | medium | 本样本相符 | 18.19 秒 |
| gpt-image-2.5-sunburst | 1024x1024 | 1024x1024 | medium | 本样本相符 | 22.45 秒 |
| gpt-image-2.5-sunburst | 1024x1536 | 1024x1536 | medium | 本样本相符 | 15.20 秒 |
| gpt-image-2.5-sunburst | 1536x864 | 1536x864 | medium | 本样本相符 | 16.87 秒 |

首轮合计：9 张中 7 张尺寸相符、2 张不符；6 张质量声明相符、3 张质量未知、0 张声明 low。每个组合只测试一次，不把这个比例当作长期可靠率。首轮没有 low/high 对照，后续对照见 §6。

## 4. 路由、下载和证据完整性

按用户规定先运行认证预检，结果 eligible，再使用 `codex-config-imagegen` launcher 发起每次生成。任务专用、需鉴权的回环适配器将 launcher 的 Responses 图像工具字段转成上述 Images 请求；实际生成供应商为 mux.la，未经过 Sub2API。任务专用 launcher 顶层 model 为当前配置的 `gpt-6.1-terra`，图像模型显式选择表中名称；适配器只发 Images POST，没有额外文本模型调用。全局 Codex 配置及既有本机服务账户未修改。

9 个响应均提供 `data[].url`，没有 base64。它们与官方 GPT Image 默认 base64 响应形态不同，属于第三方接口行为。launcher 因只识别 base64 而退出 1；这不等于上游生成失败。测试随后下载**同一已生成资产**，未重复生图，所有下载均通过 HTTPS 证书校验、只访问解析为公网地址的 URL、不发送 API Key、不跟随重定向。

gpt-image-2 横图首次资产 GET 返回 403；加入常规 User-Agent/Accept 后对同一 URL 下载成功。其他资产也按同样方式成功下载。重试下载不产生新的 Images POST。flare/sunburst 的带签名资产 URL 保留在私有响应中，报告不公布签名或完整链接；不能由资产域名推定真实模型身份。

所有 9 张图片已逐张查看，内容为红陶瓷杯照片，无明显破损；视觉检查不用于判定 medium。gpt-image-2 的正方形响应另带 width/height=1254/1254，和实际 PNG 一致；竖图 width/height=1024/1536，和 PNG 一致。横图 usage 自报 estimated；不使用 token 数倒推质量，也不认为其他 usage 的存在能证明其精确计费。

原始请求、响应、图片与凭据均保存在被 Git 忽略的私有目录 `.dev/bug-gpt-image-mux-20261105/`，不进入版本管理。`official_probe.py` 对每个测试标签拒绝重复执行，不自动重试。`validation-summary.json` 汇总 9 次单次 POST、逐张 PNG 实际尺寸与 SHA-256；`official-sources-manifest.json` 保存本轮官方正文的 URL、日期和摘要。

关键图片 SHA-256：

| 样本 | SHA-256 |
| --- | --- |
| gpt-image-2 / 1024x1024 | `7088068e8221f02f95e8a7e45563c8a2c21b7d78082361d25265b0754ab5f7df` |
| gpt-image-2 / 1536x864 | `0be7af4d6dfc94a238f49b8d2e1c4dedc240e9493718f1bf7b902b09e1a9b991` |
| flare / 1536x864 | `447a5868001d43dd103022b6642f90705126e4839839e4e2f6799e02df49a53f` |
| sunburst / 1536x864 | `7dd0297d24b5c0d357362b94a3e6ccd8e183005735ecda5d79c3fb9d0c760620` |

## 5. 原因判断与处理建议

尺寸问题在规范请求、绕过 Sub2API 的直连测试中依然出现，所以 mux.la 当前 gpt-image-2 通道本身无法稳定兑现这三个显式尺寸。`1254x1254`、`1672x941` 的像素面积接近 1536x1024，与历史订阅通道的固定像素预算现象相容，但没有 mux.la 的最终出站请求/原始后端日志，不能据此断言私有路由、具体模型或哪一层改写了尺寸。

要继续使用 gpt-image-2，需供应商修正该通道并用相同请求复验；不能仅靠提示词强调正方形、回显 size 或将图片后处理成指定尺寸宣称原生参数已支持。质量未知时不得由网关补写 medium。

若业务允许使用 flare/sunburst，可以基于本轮通过的三种尺寸及 medium 声明做受控接入，并持续核对实际像素和质量声明。模型目录、原名及响应 model 声明均来自第三方，不能保证其与 OpenAI 官方后端完全相同。本轮未改业务源码、未重新部署服务、未替换本地账户、未修改生产配置；测试实际发生于 mux.la，不能当作原 Relinx 订阅通道已经修复。

## 6. 扩展尺寸 × 质量矩阵（当前结果）

### 6.1 范围与执行

在首轮同一 Key、同一 prompt、同一端点与规范字段下，覆盖 `1024x1024`、`1024x1536`、`1536x864`、`1536x1024`、`2048x1152`，分别组合 low、medium、high；这五种尺寸均满足已核对的官方约束，最大面积 2359296 像素，不属于文档所述大于 2560x1440 的实验性分辨率。

三个模型共 45 个唯一组合：已有 9 个 medium 样本直接复用，新增 36 次 Images POST；最多并发 3，每个请求前均经 launcher 认证预检，不自动重试生成。额外下载只读取同一已生成资产。未测试 auto、2.5 的 xhigh/max、edits、stream 或 n>1，不将结果扩展到这些模式。

### 6.2 汇总

| 模型 | 组合 / 图片数 | 尺寸相符 | 尺寸不符 | 质量声明相符 | 质量未知 | 尺寸与声明均相符 |
| --- | --- | --- | --- | --- | --- | --- |
| gpt-image-2 | 15 | 6 | 9 | 0 | 15 | 0 |
| gpt-image-2.5-flare | 15 | 15 | 0 | 15 | 0 | 15 |
| gpt-image-2.5-sunburst | 15 | 15 | 0 | 15 | 0 | 15 |
| 合计 | 45 | 36 | 9 | 30 | 15 | 30 |

新增 36 次单独统计：36 次 HTTP 200、36 张图片，29 张尺寸相符、7 张不符；24 张质量声明相符、12 张缺失。与首轮去重合并才得到上表，不是新增 45 次。全量无生成失败、无缺失图片、无质量声明冲突；medium 没有被声明为 low。每个质量档位各 15 个组合，均为 12 个尺寸相符、3 个不符，10 个质量声明相符、5 个未知。

### 6.3 完整组合结果

每个单元格依次为「实际像素 / 响应质量声明」；缺失表示没有质量声明。**粗体表示实际像素不符合该行请求尺寸**。质量声明相符仍不是独立的后端计算档位认证。

| 模型 | 请求尺寸 | 请求 low 的结果 | 请求 medium 的结果 | 请求 high 的结果 |
| --- | --- | --- | --- | --- |
| gpt-image-2 | 1024x1024 | **1254x1254** / 缺失 | **1254x1254** / 缺失 | **1254x1254** / 缺失 |
| gpt-image-2 | 1024x1536 | 1024x1536 / 缺失 | 1024x1536 / 缺失 | 1024x1536 / 缺失 |
| gpt-image-2 | 1536x864 | **1672x941** / 缺失 | **1672x941** / 缺失 | **1672x941** / 缺失 |
| gpt-image-2 | 1536x1024 | 1536x1024 / 缺失 | 1536x1024 / 缺失 | 1536x1024 / 缺失 |
| gpt-image-2 | 2048x1152 | **2048x1153** / 缺失 | **2048x1153** / 缺失 | **2048x1153** / 缺失 |
| gpt-image-2.5-flare | 1024x1024 | 1024x1024 / low | 1024x1024 / medium | 1024x1024 / high |
| gpt-image-2.5-flare | 1024x1536 | 1024x1536 / low | 1024x1536 / medium | 1024x1536 / high |
| gpt-image-2.5-flare | 1536x864 | 1536x864 / low | 1536x864 / medium | 1536x864 / high |
| gpt-image-2.5-flare | 1536x1024 | 1536x1024 / low | 1536x1024 / medium | 1536x1024 / high |
| gpt-image-2.5-flare | 2048x1152 | 2048x1152 / low | 2048x1152 / medium | 2048x1152 / high |
| gpt-image-2.5-sunburst | 1024x1024 | 1024x1024 / low | 1024x1024 / medium | 1024x1024 / high |
| gpt-image-2.5-sunburst | 1024x1536 | 1024x1536 / low | 1024x1536 / medium | 1024x1536 / high |
| gpt-image-2.5-sunburst | 1536x864 | 1536x864 / low | 1536x864 / medium | 1536x864 / high |
| gpt-image-2.5-sunburst | 1536x1024 | 1536x1024 / low | 1536x1024 / medium | 1536x1024 / high |
| gpt-image-2.5-sunburst | 2048x1152 | 2048x1152 / low | 2048x1152 / medium | 2048x1152 / high |

逐组合的 HTTP、实际像素、质量声明、耗时、图片字节数及 SHA-256 可下载 [45 行脱敏 CSV](BUG_MUX_IMAGE_SIZE_QUALITY_MATRIX_20261105.csv)。CSV 不含 Key、提示词、完整资产 URL 或签名信息。

### 6.4 新发现与证据边界

gpt-image-2 的本轮尺寸异常在 low、medium、high 都出现，不能把问题局限为 medium 的取值或某个质量档位与尺寸的组合非法。`2048x1152 → 2048x1153` 只有一像素差异，仍然不满足精确像素要求，且输出高度不再是 16 的倍数；不能因为视觉难以分辨而算通过。这与中间层重算尺寸/取整的假设相容，但没有供应商原始后端证据，无法确定具体步骤。

15 个 gpt-image-2 样本的质量均未知；改变 quality 后图片和部分清晰度有所不同，不足以证明官方档位、真实内部计算预算或质量参数已被正确处理。flare/sunburst 共 30 个样本能确认图片精确像素及上游声明相符，适合作为本轮需求的候选通道，但仍需供应商后端证据才能认证真实计算档位。不能依据 token 估计或耗时排序认定质量等级；本轮 sunburst 的 low 竖图单次耗时约 229 秒（含资产下载），也没有为较慢样本自动再生成。

### 6.5 保存与验证

私有目录不变。新增 `matrix-plan.json` 记录 45 个组合和复用标志，`matrix-progress.json` 记录 36 次新增执行结果，`matrix-validation-summary.json` 汇总全量及新增样本，`matrix-results.csv` 为私有基础导出；逐请求原始 JSON、响应和图片使用 `matrix-*` 标签。每个生成记录只有一次上游 POST，已有出站请求即禁止重复标签发起生成。

45 张原始 PNG 均已完整解码、核对宽高与 SHA-256，45 个哈希彼此不同。已用 view_image 查看原图及按模型/尺寸/质量标注的检查拼图，所有样本内容为红陶瓷杯照片；拼图只供视觉检查，原图未重采样或更改，像素判定始终读取原图字节。图片清晰度差异不充当质量协议证明。

文档矩阵和脱敏 CSV 均对照私有摘要逐格核验；架构索引、链接、围栏与 diff 检查通过。仅更新测试资料和文档索引，无业务代码、数据库、运行账户或生产部署改动。未把本轮 mux.la 的通过样本视为原 Relinx 订阅通道已修复。

## 7. 第二个 mux.la Key：9 个典型组合复测

### 7.1 范围和结论

2026-11-05，按用户新提供的 mux.la Key 和“总量 10 个以内”的要求，**只发起 9 次 Images 生成请求**，每个组合一次，不复用首个 Key 的结果、不重试生成、不额外加测。另有一次只读 `/v1/models`，返回 HTTP 200，仍列出同名三个模型；模型查询没有生成图片。

本轮三个模型各 3 个样本，**9 次全部 HTTP 200，各返回 1 张 PNG，实际像素和质量声明全部相符，没有 medium→low 冲突**。因此第二个 Key 的本轮典型组合满足尺寸和质量声明要求，包括之前失败的 gpt-image-2 正方形及客户原始横图；该结论不等同于证明内部计算档位、官方模型身份或长期稳定性。

### 7.2 逐项结果

| 模型 | 请求 size | 请求 quality | 实际像素 | 响应 quality | 判定 | 生成响应耗时 |
| --- | --- | --- | --- | --- | --- | --- |
| gpt-image-2 | 1024x1024 | medium | 1024x1024 | medium | 相符 | 38.35 秒 |
| gpt-image-2 | 1536x864 | medium | 1536x864 | medium | 相符 | 30.78 秒 |
| gpt-image-2 | 1024x1536 | high | 1024x1536 | high | 相符 | 37.98 秒 |
| gpt-image-2.5-flare | 1024x1024 | medium | 1024x1024 | medium | 相符 | 31.96 秒 |
| gpt-image-2.5-flare | 1536x864 | medium | 1536x864 | medium | 相符 | 20.60 秒 |
| gpt-image-2.5-flare | 1024x1536 | low | 1024x1536 | low | 相符 | 25.13 秒 |
| gpt-image-2.5-sunburst | 1024x1024 | medium | 1024x1024 | medium | 相符 | 26.41 秒 |
| gpt-image-2.5-sunburst | 1536x864 | medium | 1536x864 | medium | 相符 | 24.10 秒 |
| gpt-image-2.5-sunburst | 1024x1536 | high | 1024x1536 | high | 相符 | 31.82 秒 |

这是 9 个典型组合，不是完整交叉矩阵。三个模型的正方形/原始横图 medium 均覆盖；竖图分别抽样 high、low、high。没有测试本 Key 的其他尺寸或质量组合，不把另一个 Key 的通过记录算作本 Key 已验证。

### 7.3 与首个 Key 的差异

| gpt-image-2 相同请求 | 首个 Key 的实际结果 | 第二个 Key 的实际结果 |
| --- | --- | --- |
| 1024x1024 / medium | 1254x1254，quality 缺失 | 1024x1024，声明 medium |
| 1536x864 / medium | 1672x941，quality 缺失 | 1536x864，声明 medium |
| 1024x1536 / high | 1024x1536，quality 缺失 | 1024x1536，声明 high |

新 Key 的 9 个响应均直接提供 `b64_json`，顶层 size/quality 均声明并与图片字节一致，model 字段未声明；首个 Key 的 45 个响应提供资产 URL。可以确认本次观察到接口行为不同，不能仅据此断言差异一定由 Key 分组、某条后端路由或供应商更新造成。实际采用通道时应保留 Key/账户对应关系并校验输出，不能按域名或同名模型统一假定能力。

### 7.4 方法与证据

沿用 §2 的官方规范请求与同一红陶瓷杯 prompt，不发送 response_format。继续按用户要求预检并使用 codex-config-imagegen launcher，任务专用适配器只发 `https://mux.la/v1/images/generations`，绕过 Sub2API；顶层任务模型仍为 `gpt-6.1-terra`，图像模型显式选择表中原名，无文本模型调用、图片缩放或标签回填。

本轮 base64 图片已由 launcher 保存，完整解码并从 PNG 字节头读取宽高，核对 SHA-256；9 张原始文件均存在。已用 view_image 查看带模型/参数标注的检查拼图，各图内容为红陶瓷杯照片，无明显破损；拼图仅供检查，原图不更改。不使用视觉差异、tokens 或响应标签独立证明内部计算档位。

本 Key 凭据、请求、原始响应、图片和日志单独保存在被 Git 忽略的 `.dev/bug-gpt-image-mux-key2-20261105/`，不覆盖首个 Key 的证据。`plan.json` 固定 9 个组合，`progress.json` 保存执行结果，`validation-summary.json` 保存 9 次单次 POST、每图实际尺寸/质量声明与 SHA-256。

gpt-image-2 正方形 medium 图片 SHA-256 为 `4bacd5b34e2546f88db06a85c5c4a47986345d9ac427a954b4fd098f825fc00c`；原始横图 medium 为 `fbb26f3b1973f152ce6689daa30e069b5d18425441cc366c5bdf179ec4081ac2`。新 Key 未写入已有本机账户或全局 Codex 配置，未部署或修改生产服务。
