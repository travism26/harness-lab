# Plain HTTP requests in Anthropic's format, not Anthropic's Python SDK

The harness sends its requests to the model as plain HTTP POSTs with Python's standard library (`projects/harness/src/harness_lab/client.py`), using Anthropic's Messages request and response format. It does not use Anthropic's Python SDK.

- The series teaches what a harness is made of. The request body, the `tool_use` and `tool_result` blocks and the stop reason are the loop, so the reader should see them rather than an SDK's objects.
- The endpoint is OpenRouter's, set by a setting (see [0002](0002-openrouter-only-provider-and-sole-credential.md)), and the model may be any OpenRouter model name, not only Claude. A plain request keeps the endpoint address, key and model as inputs. The SDK is built around Anthropic's own service.
- It adds no dependency to the lock file.

The cost is that the harness does its own error handling and has no retries or streaming. That is acceptable for a small teaching loop. This is separate from [0001](0001-raw-api-loop-without-agent-sdk.md), which is about the Agent SDK's loop; this one is about the client library under our own loop.
