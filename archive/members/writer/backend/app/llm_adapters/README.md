# LLM Adapter Profiles

Provider adapter profiles describe how a provider-compatible endpoint differs
from the default OpenAI or Anthropic request/response shape.

They are loaded from:

- `members/writer/backend/app/llm_adapters/*.jsonc`
- `LAMWRITER_MEMBER_RESOURCE_DIR/llm_adapters/*.jsonc`
- `LAMTOOLS_RUNTIME_ROOT/members/writer/llm_adapters/*.jsonc`
- `LAMWRITER_LLM_ADAPTER_DIR`
- `%APPDATA%/LamWriter/llm-adapters`

Profiles loaded later override profiles with the same `id`, so user-level
directories can override packaged defaults.

API keys stay in provider configuration or environment variables. Do not put
secrets in these files.

Provider or model `extra` may select a profile:

```json
{
  "adapter_profile": "xfyun-coding-plan"
}
```

Provider or model `extra` may also override a profile:

```json
{
  "adapter_profile_override": {
    "request": {
      "body": {
        "enable_thinking": true
      }
    }
  }
}
```

Use profiles for endpoint paths, request-only fields, thinking parameters,
unsupported fields, and stream/non-stream response field paths.
