# Qoder 协议逆向研究结果

> 研究日期：2026-08-06
> 来源：反编译 `@qodercn-ai/qoderclicn@1.1.16`（npm 包，66MB，`qoderclicn.js` 单文件 bundle）+ 对 `openapi.qoder.sh` / `api2-v2.qoder.sh` / `api3.qoder.sh` 的实测抓包
> 关联项目：QoderGateway（Python 版 qoder2api，本仓库）

---

## 0. 结论速览

- Qoder 存在**两代协议**：老版（`center.qoder.sh` + COSY 签名，cubk1/qoder2api 及本仓库 QoderGateway 所用）和新版（`openapi.qoder.sh` / `api2-v2.qoder.sh` + 纯 `Bearer` token，Qoder CLI 现行）。
- 新版协议是 **OpenAI 兼容**的：`POST https://api2-v2.qoder.sh/model/v1/chat/completions`，仅需 `Authorization: Bearer <security_oauth_token>`，无需任何签名。
- **同一个 `security_oauth_token`（`dt-` 前缀）在老版和新版端点上都能用**（已实测：两者都返回 200 并正常出流）。
- 登录/换取 token 走 **PKCE device flow**：`GET https://openapi.qoder.sh/api/v1/deviceToken/poll?nonce=...&verifier=...&challenge_method=S256` 轮询，**404 = 等待用户授权**（非错误），**200 = 授权完成返回 token 凭据**。

---

## 1. Token 数据结构（deviceToken poll 的 200 响应）

```json
{
  "id": "019fd6c9-...",
  "token": "dt-0IUJEMYfFUFu9beAsx0cMaR9",
  "user_id": "019ec623-...",
  "code_challenge": "h-1Oi6gLAOdnbUD2orefq3JxJz7j4iGjUobnD8JQJ-8",
  "code_challenge_method": "S256",
  "nonce": "7554805c-e90c-4110-87f8-579cbf3e16a8",
  "expires_at": "2026-09-05T11:16:15Z",
  "refresh_token_id": "019fd6c9-...",
  "refresh_token": "drt-Wq7deftCwhAJbQ7geTmyPrOL",
  "created_at": "2026-08-06T11:16:15Z",
  "updated_at": "2026-08-06T11:16:15Z",
  "expires_in": 2591999994,
  "refresh_token_expires_in": 31103999996,
  "refresh_token_expires_at": "2027-08-01T11:16:15Z"
}
```

关键字段到项目代码的映射：

| 字段 | 含义 | 写入 QoderGateway `accounts` 表的列 |
|---|---|---|
| `token` (`dt-`) | security_oauth_token | `security_oauth_token` |
| `refresh_token` (`drt-`) | refresh token | `refresh_token` |
| `user_id` | 用户 uid | `uid`（主键） |
| `code_challenge` / `nonce` | 登录流程内部参数，请求 API 时用不到 | 忽略 |
| `expires_at` | dt- 有效期 | 到期后需用 drt- 刷新 |

---

## 2. 新版协议端点（openapi.qoder.sh 域，纯 Bearer）

| 端点 | 方法 | 用途 | 请求头/体 |
|---|---|---|---|
| `https://openapi.qoder.sh/api/v1/deviceToken/poll` | GET | 轮询 device 授权结果 | `Accept: application/json` |
| `https://openapi.qoder.sh/api/v1/userinfo` | GET | 获取用户信息（uid/name/email/org） | `Authorization: Bearer <token>` |
| `https://openapi.qoder.sh/api/v1/jobToken/exchange` | POST | PAT → job token | body `{"personal_token": "<PAT>"}` |
| `https://openapi.qoder.sh/api/v1/jobToken/refresh` | POST | refresh token 换新 | body `{"refresh_token": "<drt-...>"}` |
| `https://openapi.qoder.sh/api/v1/serviceToken/exchange` | POST | service account key 换 token | body `{"grant_type":"client_credentials","audience":"qoder","scope":"...","ttl_seconds":3600}`，头 `Authorization: Bearer <serviceKey>` |
| `https://api2-v2.qoder.sh/model/v1/chat/completions` | POST | **OpenAI 兼容 chat 接口** | `Authorization: Bearer <token>`、`Content-Type: application/json`、`Accept: text/event-stream`、`X-Request-ID`、`X-Session-ID` |

### chat/completions 请求体（新版）

```json
{
  "model": "lite",
  "messages": [{"role": "user", "content": "hi"}],
  "stream": true,
  "stream_options": {"include_usage": true},
  "metadata": {
    "context": {
      "request_id": "<uuid>",
      "request_set_id": "<uuid>",
      "session_id": "<uuid>",
      "task_id": "common",
      "client_type": "qodercli"
    }
  }
}
```

- 响应为 SSE，标准 OpenAI `chat.completion.chunk` 格式，`raw_usage` 携带 token 统计。
- `tools`、`stop`、`max_tokens`、`temperature`、`reasoning_effort`、`patches`、`custom_model` 均可选传入。
- 401/403 时客户端会 `forceRefreshToken`（用 drt- 刷新）后重试一次。

### 域名映射（国际版，国内为 `.com.cn`）

```js
inference : api2-v2.qoder.sh      (新版 chat)
center    : center.qoder.sh       (老版，QoderGateway 所用)
openapi   : openapi.qoder.sh      (鉴权/用户/兑换)
sse/chat  : api3.qoder.sh         (老版 agent_chat_generation，QoderGateway 所用)
```

---

## 3. 老版协议对照（QoderGateway 当前实现）

- 兑换：`POST https://center.qoder.sh/algo/api/v3/user/jobToken?Encode=1`，body `{"payload": "<QoderEncoding 编码>", "encodeVersion": "1"}`，`personalToken` 字段放 PAT。
- 编码（`src/qoder2api/encoding.py` 与上游 Java 一致）：**自定义 alphabet base64 + 三段重排**，无 XOR。alphabet：`_doRTgHZBKcGVjlvpC,@aFSx#DPuNJme&i*MzLOEn)sUrthbf%Y^w.(kIQyXqWA!`，pad `$`。
- 签名：`signature = md5("cosy&d2FyLCB3YXIgbmV2ZXIgY2hhbmdlcw==&<RFC1123 GMT date>")`；`appcode = "cosy"`。
- 请求头：`cosy-machinetoken`、`cosy-machinetype`、`cosy-machineid`、`login-version: v2`、`cosy-version: 0.1.43`、`cosy-clienttype: 5`、UA `Go-http-client/2.0`。
- chat：`POST https://api3.qoder.sh/algo/api/v2/service/pro/sse/agent_chat_generation?FetchKeys=llm_model_result&AgentId=agent_common&Encode=1`，`Authorization: Bearer COSY.<payloadB64>.<md5sig>`，body 为 `template_base()`（`src/qoder2api/bridge.py`）。
- 实测：**`dt-` 前缀的 security_oauth_token 在老版端点上同样有效**（用 QoderGateway 现有代码构造 `AuthIdentity` 直接成功）。

---

## 4. deviceToken 认证流程（PKCE device flow）

实现位于 qoderclicn bundle 的 `GfI()` 函数，共 4 步：

### 4.1 生成 PKCE 参数

```js
verifier  = 随机 43~128 个字符，字符集 "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"（66 字符）
challenge = BASE64URL(SHA256(verifier))   // base64 后 + → -, / → _, 去掉尾部 =
```

### 4.2 生成 nonce

`nonce = randomUUID()`（UUID v4）。

### 4.3 授权 URL（浏览器打开）

```
https://qoder.com/device/selectAccounts?challenge=<challenge>&challenge_method=S256&nonce=<nonce>&machine_id=<machineId>&client_id=<clientId>
```

- `client_id`（从混淆解密得到）：`e883ade2-e6e3-4d6d-adf7-f92ceff5fdcb`（默认）或 `e93fe488-5778-4c35-a6fc-0f54ed7b3139`
- 用户登录 → 选账号 → 同意 → 服务端绑定 `challenge ↔ nonce ↔ 用户`

### 4.4 轮询 poll（循环）

```js
params = new URLSearchParams({ nonce, verifier, challenge_method: "S256" })
url = `https://openapi.qoder.sh/api/v1/deviceToken/poll?${params}`

while (Date.now() < deadline) {          // deadline = now + 300000ms（5 分钟超时）
    resp = fetch(url, { headers: {Accept: "application/json"},
                        markErrorStatus: s => s !== 404 })   // 404 不算错误
    if (resp.status === 404) { await sleep(1000); continue } // 1 秒一轮
    if (!resp.ok) throw ...
    data = await resp.json()
    if (data.token && typeof data.token === "string") return data   // 200 → 凭据
}
throw "timeout"
```

**状态码语义**：
- `404` = 用户尚未完成授权（设计内的"等待中"），每 1 秒重试，最长 5 分钟
- `200` = 授权完成，服务端校验 `SHA256(verifier) == challenge` 后返回 §1 的凭据 JSON
- 其他非 2xx = 真实错误

---

## 5. 混淆字符串解密方法（复现用）

bundle 文件第一行的解密函数：

```js
const _$d = (s, k = "syJkkdK5Dxwd") => {
  const b = Buffer.from(s, "base64");
  for (let i = 0; i < b.length; i++) b[i] ^= k.charCodeAt(i % k.length);
  return b.toString();
};
```

- 算法：base64 解码 → 用 key `syJkkdK5Dxwd` 循环 XOR。
- 已验证解出的常量：
  - client_id（两个）：`e883ade2-e6e3-4d6d-adf7-f92ceff5fdcb`、`e93fe488-5778-4c35-a6fc-0f54ed7b3139`
  - verifier 字符集：`ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~`

---

## 6. 关键常量汇总（qoderclicn@1.1.16）

| 常量 | 值 | 含义 |
|---|---|---|
| `cxn` | `1000` | 轮询间隔 ms |
| `vfI` | `300000` | 轮询总超时 ms（5 分钟） |
| `HfI` | `3` | 网络错误重试次数 |
| `client_id` | 见 §4.3 | device flow 客户端标识 |
| verifier 字符集 | 66 字符 | PKCE verifier 合法字符 |

---

## 7. 实测记录（2026-08-06，token 为 `dt-` 前缀）

1. `GET openapi.qoder.sh/api/v1/userinfo`（Bearer dt-）→ **200**，返回用户 `bzym2`（GitHub SSO），`id` 与 poll 响应的 `user_id` 一致。
2. `POST api2-v2.qoder.sh/model/v1/chat/completions`（Bearer dt-，model=lite）→ **200**，SSE 流式正常出内容，带 `raw_usage`。
3. QoderGateway 老版路径（COSY 签名 + api3.qoder.sh agent_chat_generation，`security_oauth_token`=dt-）→ **200**，流式正常。
4. `jobToken` 老兑换端点把 `dt-`/`drt-` 当 `personalToken` 提交 → **401 `personal token is invalid`**（PAT 与 device token 是不同凭证，互不通用）。

---

## 8. 安全注意事项

- `verifier` + `nonce` 组合等于兑换凭证：poll URL 泄露给第三方可导致账号 token 被冒领，**不得外传**。
- `dt-` / `drt-` token 已明文存入 `~/.qoder/qoder2api.db`，该库 = 完整登录身份，注意文件权限与备份。
- QoderGateway 目前**未实现** token 自动刷新；`dt-` 过期后需用 `POST openapi.qoder.sh/api/v1/jobToken/refresh`（body `{"refresh_token": "<drt-...>"}`）换新后更新数据库。

---

## 9. 后续可做（未实施）

- [ ] QoderGateway 增加新版协议适配：`bridge.py` 新增 `api2-v2.qoder.sh/model/v1/chat/completions` 路径（纯 Bearer，无需 COSY 签名）
- [ ] 增加 token 自动刷新：定时/请求前检查 `expires_at`，用 `jobToken/refresh` 换新并回写数据库
- [ ] 自动化 device flow 脚本：生成 verifier/challenge → 打印授权 URL → 轮询 poll → 拿到凭据自动入库

---

## 10. 协议路由决策（2026-09-20 更新，实测）

> 结论先行：**所有模型统一走老版 api3 协议**（COSY 签名 + `X-Model-Key` + `encoding.encode` 编码 body + tool_calls 分片合并）。
> 新版 api2-v2 协议**保留观察**：未来若全模型可用再切换，当前不作为主路径。

### 10.1 模型可用性实测（Reqable 抓包 IDE + 单账号脚本实测）

| 协议通道 | lite | qfmodel | 其余 11 个目录模型 |
|---|---|---|---|
| 新版 `api2-v2.qoder.sh/model/v1/chat/completions` | ✅ 200 | ❌ 402 `{"code":116,"error":"quota exceeded"}` | ❌ 402 |
| 老版 `api3.qoder.sh/.../agent_chat_generation` | ✅ 200 | ✅ 200（2.8s 出字，工具调用全链路通过） | ❌ HTTP 200 后**挂起零输出**（auto 给到 150s 仍无首 token） |

- `qfmodel` 是 Qoder IDE（0.3.4 / Cosy 1.1.57）的默认模型 key：抓包证实 IDE 请求头为 `X-Model-Key: qfmodel` + `X-Model-Source: system`，SSE 响应 `model` 字段为 `auto`（档位名，非具体模型 id）。
- **其余 11 个目录模型（auto/ultimate/performance/efficient/qmodel/qmodel_latest/dmodel/dfmodel/gm51model/kmodel/mmodel）不可用是账号问题，不是协议问题**：老版协议下它们连接被接受但无限挂起（不报错），新版协议下至少返回 402；推测账号等级/配额池为空，等账号权限变化后同一套老版代码即可直接生效，无需改协议。
- 复测脚本：`scripts/test_qfmodel_old.py`（老版多模型）、`scripts/test_one_model.py`（单模型长超时）、`scripts/test_qfmodel_tools.py`（工具调用链路）、`scripts/test_qfmodel.py`（新版对照）。原始日志 `logs/old_proto_all_models.log`。

### 10.2 路由规则

```
请求 model key
   └─ 一律走老版 api3：COSY 签名（auth.bearer_headers）+ template_base() 构造 body
      + model_config.key / chat_context.extra.modelConfig.key 双写
      + X-Model-Key / X-Model-Source: system 头
      + encoding.encode() 编码 body
      + 响应解析复用 bridge.ToolCallAccumulator（tool_calls 分片按 index 合并）
      + 过滤 reasoning_content 空帧
```

### 10.3 必须注意的坑

1. **挂起失败模式**：老版协议下无权限/无配额模型不报错、不吐字，无限挂起。网关侧**必须加读超时兜底**（建议 60s 无首 token 即断开并切换账号重试），否则连接会被无限占用。
2. **tool_calls 分片**：老版 SSE 的 tool_calls 首帧含 `id`+`name`，后续帧仅 `arguments` 增量，必须按 `index` 合并才能得到完整参数。
3. **响应 `model` 字段是档位名**（如 `auto`），不是具体模型 id，网关回给客户端的 model 建议用请求时的 key。
4. `usage` 在最后独立帧返回，含 `credits` 计费字段；`billable: false` 表示该帧不计费。

> **实现状态（2026-09-20 已落地）**：`bridge.py` 已切老版协议（`USE_OLD_PROTOCOL` 默认 1），
> 首字超时（`FIRST_TOKEN_TIMEOUT=60s`，只认非空非 SSE 注释行）、流中读超时（`STREAM_READ_TIMEOUT=120s`）、
> 错误帧识别（`UpstreamErrorFrame`，body 含 `code/message` 无 `choices`，实测不可用模型 0.8s 返回 code=112+pricingUrl）、
> 挂起识别（`UpstreamHangError`）均已实现；`app.is_account_error` 对这两个异常返回 True，触发账号轮换。
> 环境变量可调：`QODER_USE_OLD_PROTOCOL` / `QODER_FIRST_TOKEN_TIMEOUT` / `QODER_STREAM_READ_TIMEOUT` / `QODER_TOTAL_TIMEOUT`。

### 10.4 未来切换新版的触发条件

- [ ] 上游新版 api2-v2 通道对非 lite 模型返回 200（不再 402/挂起）
- [ ] 或账号侧配额/权限在新版通道生效
- [ ] 满足任一条件后，评估把快路径切回新版（新版优势：无签名、响应快、无挂起风险，`lite` 档实测快 3~6 倍）

---

## 11. 模型目录（QODER_MODELS）

后端目录定义在 `src/qoder2api/bridge.py`（`QODER_MODELS` 常量），经 `GET /v1/models` 发现端点（`src/qoder2api/app.py`）对外暴露，供 OpenAI 兼容客户端与前端 Playground 下拉使用。chat 请求的 model 为透传，不做硬校验。

| 分类 | key |
|---|---|
| 档位模型 | `auto` / `ultimate` / `performance` / `efficient` / `lite` |
| frontier 模型 | `qmodel` / `qmodel_latest` / `dmodel` / `dfmodel` / `gm51model` / `kmodel` / `mmodel` |

> 注：`qfmodel`（IDE 默认）**不在**上述目录中——它不在 keirouter 的清单里，是 2026-09-20 抓包新发现的 key。若要支持 IDE 默认档位，需把它补进 `QODER_MODELS`。

---

## 12. 账号级代理（2026-09-21 落地）

每个账号可单独配置上游代理，控制台账号池逐账号编辑（`vpn_lock` 按钮）。

| 字段 | 列 | 说明 |
|---|---|---|
| 启用代理 | `accounts.proxy_enabled` | 1=走自己的代理；0=回退全局 |
| 代理地址 | `accounts.proxy_url` | `http://` / `socks5://` |
| 代理账号 | `accounts.proxy_username` | 可空 |
| 代理密码 | `accounts.proxy_password` | 可空；**接口不回显**，只回 `proxy_password_set` 标志；保存时留空=保留原值 |

**优先级**：账号启用且有地址 → 账号代理；否则 → `.env` 的 `QODER_PROXY`；再否则 → 直连。
带账号密码时拼成 URL userinfo（`http://user:pass@host:port`，user/pass 做 URL 编码），因为 httpx 的代理认证只认 URL 形式。

**实现要点**：
- httpx 0.28 **没有按请求传代理的参数**，代理只能挂在 client 上 → `bridge.py` 按“代理地址”缓存一组 `AsyncClient`（相同代理共享连接池），`resolve_proxy(sess)` 决定用哪个
- `SessionContext` 新增 4 个代理字段（`auth.py`），`accounts._session_from_row` 从 DB 行挂上；改代理会失效会话缓存
- 接口：`POST /ui/accounts/proxy`（body `{uid, proxy_enabled, proxy_url, proxy_username, proxy_password?}`）
- 注册机（DrissionPage 浏览器）的代理是**另一套**，走 `.env` 的 `QODER_REGISTRAR_PROXY` / `QODER_REGISTRAR_PROXY_URL`（见 §13），与账号级代理互不影响

---

## 13. 并发与连接池（2026-09-21 落地）

四层防护，全部可用环境变量调整（见 `.env.example`）：

| 层 | 变量 | 默认 | 作用 |
|---|---|---|---|
| 全局并发闸 | `QODER_MAX_CONCURRENCY` / `QODER_GATE_WAIT` | 300 / 15s | 进程级在飞请求上限；排队超过 wait 返回 429 + `Retry-After`。流式请求全程持闸，随流结束释放 |
| 单账号并发闸 | `QODER_ACCOUNT_CONCURRENCY` / `QODER_ACCOUNT_SLOT_WAIT` | 4 / 30s | 同一账号同时在飞的上游请求上限，超出排队；等不到槽位抛 `AccountSlotBusy` 并**顺延换账号** |
| 连接池 | `QODER_HTTP_MAX_CONNECTIONS` / `QODER_HTTP_KEEPALIVE` | 200 / 100 | 共享 `AsyncClient` 复用 TLS 连接（按代理分组），消除每请求新建 client 的握手与 TIME_WAIT churn |
| 会话缓存 | `QODER_SESSION_CACHE_TTL` | 60s | `SessionContext`（含 sqlite 读 + RSA/AES 签名）按 uid 缓存，避免在事件循环上同步阻塞；token 刷新自动失效 |

另外限流层（`ratelimit.py`）仍按 API Key 提供 RPM + 并发上限（0=不限）。
