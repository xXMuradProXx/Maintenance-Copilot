"""Verify LLMod chat tool-calling and embedding access with tiny live calls."""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
load_dotenv(ROOT / ".env")

from lib.llm_client import get_llmod_client, llmod_public_status  # noqa: E402


def main() -> int:
    status = llmod_public_status()
    print(json.dumps(status, indent=2))
    if not status["configured"]:
        print("FAILED: LLMod URL or API key is missing.")
        return 1

    client = get_llmod_client()
    chat_model = os.environ["LLMOD_MODEL"]
    embed_model = os.environ["EMBED_MODEL"]

    try:
        response = client.chat.completions.create(
            model=chat_model,
            messages=[
                {
                    "role": "user",
                    "content": "Call the diagnostic tool with status set to ok.",
                }
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "diagnostic",
                        "description": "Return the requested diagnostic status.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string", "enum": ["ok"]}
                            },
                            "required": ["status"],
                        },
                    },
                }
            ],
            tool_choice="required",
        )
        tool_calls = response.choices[0].message.tool_calls or []
        if not tool_calls or tool_calls[0].function.name != "diagnostic":
            print("FAILED: chat model did not produce the required tool call.")
            return 1
        arguments = json.loads(tool_calls[0].function.arguments or "{}")
        if arguments.get("status") != "ok":
            print(f"FAILED: unexpected tool arguments: {arguments}")
            return 1
        print(f"[ok] chat tool calling via {chat_model}")

        embedding = client.embeddings.create(
            model=embed_model,
            input=["maintenance copilot connectivity check"],
        ).data[0].embedding
        if len(embedding) != 1536:
            print(f"FAILED: expected 1536 embedding dimensions, got {len(embedding)}.")
            return 1
        print(f"[ok] 1536-dimensional embedding via {embed_model}")
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    print("LLMod chat and embedding access are working.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
