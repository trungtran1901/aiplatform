# Hướng dẫn tạo Model trong Model Registry

`model_registry` là nơi duy nhất khai báo model/provider được dùng trong
hệ thống. Không có model nào được hardcode trong code — mọi Agent chỉ
tham chiếu tới một `model_id` (UUID) trỏ vào bảng này.

Tạo model qua API:

```
POST /api/v1/models
```

## Các trường

| Trường | Bắt buộc | Ghi chú |
|---|---|---|
| `provider` | có | `"openai"`, `"anthropic"`, hoặc `"openai_like"` (xem bên dưới) |
| `model` | có | Tên model theo provider, ví dụ `gpt-4o-mini`, `claude-sonnet-4-6`, `llama3.1:70b` |
| `temperature` | không | Mặc định `0.7` |
| `max_tokens` | không | Mặc định `4096` |
| `enabled` | không | Mặc định `true` |
| `base_url` | không | URL endpoint tùy chỉnh — dùng cho model local hoặc provider khác |
| `api_key` | không | Key riêng cho entry này. Nếu để trống sẽ fallback về `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` trong `.env` |
| `extra_client_params` | không | Object JSON tùy chọn, merge thêm vào client (ví dụ `default_headers`, `organization`, timeout...) |

## 1. OpenAI chính thức

```json
POST /api/v1/models
{
  "provider": "openai",
  "model": "gpt-4o-mini",
  "temperature": 0.7,
  "max_tokens": 4096
}
```

`api_key` để trống → tự lấy từ `OPENAI_API_KEY` trong `.env`.
Muốn dùng key riêng cho entry này:

```json
{
  "provider": "openai",
  "model": "gpt-4o-mini",
  "api_key": "sk-..."
}
```

## 2. Anthropic chính thức

```json
POST /api/v1/models
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "max_tokens": 8192
}
```

Tương tự, `api_key` để trống → fallback `ANTHROPIC_API_KEY`.

## 3. Model local / OpenAI-compatible tùy chỉnh (`openai_like`)

Dùng cho: Ollama, vLLM, LM Studio, text-generation-webui, hoặc bất kỳ
provider nào expose API tương thích chuẩn OpenAI Chat Completions.

**`base_url` là bắt buộc** với `provider = "openai_like"` — thiếu sẽ bị
từ chối với lỗi `validation_failed`.

### Ví dụ: Ollama chạy local

```json
POST /api/v1/models
{
  "provider": "openai_like",
  "model": "llama3.1:70b",
  "base_url": "http://localhost:11434/v1",
  "api_key": "ollama",
  "temperature": 0.5,
  "max_tokens": 4096
}
```

> Ollama không bắt buộc API key thật, nhưng OpenAI client luôn cần một
> giá trị non-empty cho header — đặt giá trị bất kỳ (`"ollama"`,
> `"not-provided"`...) là đủ.

### Ví dụ: vLLM tự host

```json
POST /api/v1/models
{
  "provider": "openai_like",
  "model": "Qwen2.5-72B-Instruct",
  "base_url": "http://10.0.0.5:8000/v1",
  "api_key": "vllm-local"
}
```

### Ví dụ: provider OpenAI-compatible của bên thứ ba (vd Groq, Together, DeepSeek...)

```json
POST /api/v1/models
{
  "provider": "openai_like",
  "model": "deepseek-chat",
  "base_url": "https://api.deepseek.com/v1",
  "api_key": "sk-thirdparty-key"
}
```

## 4. Endpoint Anthropic-compatible tùy chỉnh

Nếu bạn có gateway/proxy nội bộ giả lập Anthropic API (ví dụ Bedrock
proxy, LiteLLM proxy chạy chế độ Anthropic), vẫn dùng `provider:
"anthropic"` và set `base_url`:

```json
POST /api/v1/models
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "base_url": "https://internal-proxy.company.com/anthropic"
}
```

`base_url` ở trường hợp này được chuyển vào `client_params.base_url` của
SDK Anthropic.

## 5. Dùng `extra_client_params` cho cấu hình nâng cao

Ví dụ cần gửi thêm header tùy chỉnh tới một proxy nội bộ:

```json
POST /api/v1/models
{
  "provider": "openai_like",
  "model": "internal-llm-v1",
  "base_url": "https://llm-proxy.internal/v1",
  "api_key": "proxy-token",
  "extra_client_params": {
    "default_headers": { "X-Tenant-Id": "enterprise-01" }
  }
}
```

Nội dung trong `extra_client_params` được merge trực tiếp (`**kwargs`)
vào constructor của client tương ứng (`OpenAIChat` / `OpenAILike` /
`client_params` của `Claude`).

## 6. Gán model cho AgentOS hoặc Agent

Sau khi tạo, lấy `id` trả về và gán vào một trong hai chỗ:

- **Mặc định toàn AgentOS** (fallback cho mọi Agent không tự set model riêng):

```json
PUT /api/v1/agent-os/{agent_os_id}
{ "default_model_id": "<model_id>" }
```

- **Riêng cho một Agent cụ thể** (override AgentOS default):

```json
PUT /api/v1/agents/{agent_id}
{ "model_id": "<model_id>" }
```

Thứ tự ưu tiên khi runtime resolve model: `Agent.model_id` →
`AgentOS.default_model_id`. Nếu cả hai đều trống, request chat sẽ lỗi
`validation_failed`.

## 7. Cập nhật / tắt model

```json
PUT /api/v1/models/{model_id}
{ "enabled": false }
```

Model bị `enabled: false` sẽ bị từ chối khi resolve (báo lỗi
`validation_failed`), dùng để tạm ngắt một endpoint mà không cần xóa
record.

```
DELETE /api/v1/models/{model_id}
```

Đây là soft delete (`deleted_at`) — record vẫn còn trong DB để các
`agent_runs` cũ tham chiếu tới vẫn hợp lệ, nhưng sẽ không xuất hiện
trong `GET /api/v1/models` hay được resolve cho run mới nữa.

## Lỗi thường gặp

| Lỗi | Nguyên nhân |
|---|---|
| `conflict` (409) khi POST | `(provider, model)` đã tồn tại — mỗi cặp provider+model chỉ có 1 record |
| `validation_failed` khi POST với `provider="openai_like"` | thiếu `base_url` |
| `validation_failed` khi chat | Agent và AgentOS đều chưa gán `model_id`/`default_model_id`, hoặc model bị `enabled=false` |
| `validation_failed`: "Unsupported model provider" | `provider` không phải `openai`, `anthropic`, hoặc `openai_like` |
