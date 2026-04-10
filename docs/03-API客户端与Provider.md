# API 客户端与 Provider

TreeCode 通过 Anthropic SDK 与 LLM 通信，并提供了重试机制和多 Provider 支持。

> 对应源码：`src/treecode/api/`

---

## 模块组成

| 文件 | 职责 |
|------|------|
| `client.py` | `AnthropicApiClient` — 流式消息客户端 + 指数退避重试 |
| `provider.py` | `detect_provider()` — 根据 URL/Model 自动检测 Provider |
| `errors.py` | 自定义异常层次：`AuthenticationFailure`, `RateLimitFailure`, `RequestFailure` |
| `usage.py` | `UsageSnapshot` — Token 计数 (input_tokens + output_tokens) |

---

## AnthropicApiClient

> 源码：[`api/client.py`](../src/treecode/api/client.py)

### 基础结构

```python
class AnthropicApiClient:
    """Thin wrapper around the Anthropic async SDK with retry logic."""

    def __init__(self, api_key: str, *, base_url: str | None = None):
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)
```

通过 `base_url` 参数支持兼容 Anthropic API 的第三方服务（如 Moonshot/Kimi）。

### 流式消息发送

```python
async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
```

返回两种事件：
- `ApiTextDeltaEvent(text=...)` — LLM 输出的文本片段（实时流式）
- `ApiMessageCompleteEvent(message=..., usage=..., stop_reason=...)` — 最终完整消息

### 底层流式实现 `_stream_once()`

```python
async def _stream_once(self, request: ApiMessageRequest):
    params = {
        "model": request.model,
        "messages": [msg.to_api_param() for msg in request.messages],
        "max_tokens": request.max_tokens,
    }
    if request.system_prompt:
        params["system"] = request.system_prompt
    if request.tools:
        params["tools"] = request.tools

    async with self._client.messages.stream(**params) as stream:
        async for event in stream:
            # 只处理 content_block_delta 中的 text_delta
            if getattr(event, "type", None) != "content_block_delta":
                continue
            delta = getattr(event, "delta", None)
            if getattr(delta, "type", None) != "text_delta":
                continue
            text = getattr(delta, "text", "")
            if text:
                yield ApiTextDeltaEvent(text=text)

        final_message = await stream.get_final_message()
```

关键实现细节：
1. 使用 `self._client.messages.stream()` 上下文管理器进行 SSE 流式通信
2. 从 `content_block_delta` 事件中只提取 `text_delta` 类型的文本
3. 最后通过 `stream.get_final_message()` 获取完整消息（包含 tool_use blocks）

---

## 重试机制

### 指数退避 + Jitter

```python
MAX_RETRIES = 3
BASE_DELAY = 1.0  # 秒
MAX_DELAY = 30.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}
```

重试延迟计算：

```python
def _get_retry_delay(attempt: int, exc: Exception | None = None) -> float:
    # 1. 优先使用 Retry-After 响应头
    if isinstance(exc, APIStatusError):
        retry_after = getattr(exc, "headers", {})
        if hasattr(retry_after, "get"):
            val = retry_after.get("retry-after")
            if val:
                return min(float(val), MAX_DELAY)

    # 2. 指数退避 + 25% 随机 jitter
    delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
    jitter = random.uniform(0, delay * 0.25)
    return delay + jitter
```

计算示例：
| 重试次数 | 基础延迟 | 带 Jitter 范围 |
|----------|----------|----------------|
| 第 1 次 | 2s | 2.0 ~ 2.5s |
| 第 2 次 | 4s | 4.0 ~ 5.0s |
| 第 3 次 | 8s | 8.0 ~ 10.0s |

### 可重试错误判断

```python
def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, APIStatusError):
        return exc.status_code in {429, 500, 502, 503, 529}
    if isinstance(exc, APIError):
        return True  # 网络错误可重试
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    return False
```

### 重试流程

```python
async def stream_message(self, request):
    last_error = None
    for attempt in range(MAX_RETRIES + 1):  # 最多 4 次（1 + 3 重试）
        try:
            async for event in self._stream_once(request):
                yield event
            return  # 成功
        except TreeCodeApiError:
            raise  # 认证错误不重试
        except Exception as exc:
            last_error = exc
            if attempt >= MAX_RETRIES or not _is_retryable(exc):
                raise _translate_api_error(exc)
            delay = _get_retry_delay(attempt, exc)
            log.warning("API request failed (attempt %d/%d), retrying in %.1fs", ...)
            await asyncio.sleep(delay)
```

---

## 错误翻译

原始 Anthropic SDK 异常 → TreeCode 自定义异常：

```python
def _translate_api_error(exc: APIError) -> TreeCodeApiError:
    name = exc.__class__.__name__
    if name in {"AuthenticationError", "PermissionDeniedError"}:
        return AuthenticationFailure(str(exc))
    if name == "RateLimitError":
        return RateLimitFailure(str(exc))
    return RequestFailure(str(exc))
```

异常层次：
```
TreeCodeApiError (基类)
├── AuthenticationFailure  # API Key 无效
├── RateLimitFailure       # 429 限流
└── RequestFailure         # 其他请求错误
```

---

## Provider 自动检测

> 源码：[`api/provider.py`](../src/treecode/api/provider.py)

`detect_provider()` 根据环境变量推断正在使用的 LLM 提供商：

```python
def detect_provider(settings: Settings) -> ProviderInfo:
    base_url = (settings.base_url or "").lower()
    model = settings.model.lower()

    if "moonshot" in base_url or model.startswith("kimi"):
        return ProviderInfo(name="moonshot-anthropic-compatible", ...)
    if "bedrock" in base_url:
        return ProviderInfo(name="bedrock-compatible", auth_kind="aws", ...)
    if "vertex" in base_url or "aiplatform" in base_url:
        return ProviderInfo(name="vertex-compatible", auth_kind="gcp", ...)
    if base_url:  # 其他自定义 URL
        return ProviderInfo(name="anthropic-compatible", ...)
    return ProviderInfo(name="anthropic", ...)  # 默认
```

支持的 Provider：

| Provider | 检测条件 | 认证方式 |
|----------|----------|----------|
| **Anthropic** | 无自定义 base_url | API Key |
| **Moonshot/Kimi** | URL 含 `moonshot` 或 model 以 `kimi` 开头 | API Key |
| **Bedrock** | URL 含 `bedrock` | AWS |
| **Vertex** | URL 含 `vertex` 或 `aiplatform` | GCP |
| **通用兼容** | 其他自定义 URL | API Key |

---

## SupportsStreamingMessages 协议

```python
class SupportsStreamingMessages(Protocol):
    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """Yield streamed events for the request."""
```

这是一个 `Protocol` 类型——在生产环境中由 `AnthropicApiClient` 实现，在测试中可以用 Mock 替代，实现了良好的依赖倒置。

---

## ApiMessageRequest 数据结构

```python
@dataclass(frozen=True)
class ApiMessageRequest:
    model: str                                      # 模型名称
    messages: list[ConversationMessage]              # 对话历史
    system_prompt: str | None = None                 # 系统提示词
    max_tokens: int = 4096                           # 最大输出 token
    tools: list[dict[str, Any]] = field(default_factory=list)  # 工具 Schema
```

`tools` 字段由 `ToolRegistry.to_api_schema()` 生成，包含所有工具的名称、描述和 JSON Schema。
