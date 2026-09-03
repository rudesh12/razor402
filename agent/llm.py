"""agent/llm.py — Provider shim for LLM tool calling."""
import os
import json


class LLMProvider:
    """Shim over Anthropic and Gemini tool-calling APIs."""

    def __init__(self, provider: str | None = None):
        env_provider = os.environ.get("LLM_PROVIDER", "").lower()
        if provider:
            self.provider = provider
        elif env_provider in ("gemini", "anthropic", "none"):
            self.provider = env_provider
        elif os.environ.get("GEMINI_API_KEY"):
            self.provider = "gemini"
        else:
            self.provider = "gemini"
        self._client = None
        self._recordings: list[dict] = []

    def call(self, messages: list[dict], tools: list[dict]) -> dict:
        """Make a tool-calling request to the LLM."""
        if self.provider == "anthropic":
            # User specified to skip Anthropic and use Gemini
            return self._call_gemini(messages, tools)
        elif self.provider == "none":
            raise RuntimeError(
                "LLM_PROVIDER=none. Use --replay with a fixture, or set "
                "GEMINI_API_KEY with valid API key."
            )
        else:
            return self._call_gemini(messages, tools)

    def _call_gemini(self, messages, tools):
        from google import genai
        if self._client is None:
            api_key = os.environ.get("GEMINI_API_KEY")
            self._client = genai.Client(api_key=api_key) if api_key else genai.Client()

        # Format tools if needed or pass as-is
        response = self._client.models.generate_content(
            model="gemini-2.5-flash",
            contents=messages,
            config={"tools": tools} if tools else None,
        )

        result = self._parse_gemini_response(response)
        self._recordings.append({"request": messages, "response": result})
        return result

    def _parse_anthropic_response(self, response):
        result = {"text": "", "tool_calls": []}
        for block in response.content:
            if hasattr(block, "text"):
                result["text"] += block.text
            elif hasattr(block, "type") and block.type == "tool_use":
                result["tool_calls"].append({
                    "id": block.id,
                    "name": block.name,
                    "args": block.input,
                })
        return result

    def _parse_gemini_response(self, response):
        result = {"text": "", "tool_calls": []}
        for part in response.candidates[0].content.parts:
            if hasattr(part, "text") and part.text:
                result["text"] += part.text
            elif hasattr(part, "function_call") and part.function_call:
                result["tool_calls"].append({
                    "id": f"call_{len(result['tool_calls'])}",
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args),
                })
        return result

    def save_recordings(self, path: str):
        with open(path, "w") as f:
            json.dump(self._recordings, f, indent=2)
