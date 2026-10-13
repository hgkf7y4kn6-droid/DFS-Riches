"""The language models behind the research agents, cheapest first.

1. OpenRouter's free models (OPENROUTER_API_KEY) -- OPENROUTER_MODELS, a
   comma-separated list tried in order (default: Google Gemma 4 31B, then NVIDIA
   Nemotron 3 Super 120B; OpenRouter lists no free Llama). Free models allow
   about 50 requests a day; one report uses ~13.
2. Hugging Face Inference Providers (HF_TOKEN), only with BIG_PICTURE_USE_HF=1:
   it's billed against Hugging Face credits.
3. Llama 3.2 3B on the GitHub Actions runner itself (llama.cpp on the CPU;
   the model file comes free from the Hugging Face Hub, LOCAL_GGUF_REPO /
   LOCAL_GGUF_FILE choose it). Always available, slow -- the agents send it
   compact data.

ProviderChain tries them in order. A provider that fails (rate limit, daily
cap, outage) is skipped for the rest of the run, so a capped free tier costs
one failed request, not one per call. Every provider is a LangChain chat model
or Runnable, so CrewAI (via agents.LangChainLLM) and the LangChain review
chains use whichever is active.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT = "google/gemma-4-31b-it:free,nvidia/nemotron-3-super-120b-a12b:free"
LOCAL_REPO = "bartowski/Llama-3.2-3B-Instruct-GGUF"
LOCAL_FILE = "Llama-3.2-3B-Instruct-Q4_K_M.gguf"
MAX_TOKENS = 1800


# ------------------------------------------------------------------ providers
def openrouter(model: str):
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model, base_url=OPENROUTER_BASE, api_key=os.environ["OPENROUTER_API_KEY"],
        max_tokens=MAX_TOKENS, temperature=0.2, timeout=240, max_retries=1,
        default_headers={"HTTP-Referer": "https://dfsriches.richesdigitalventures.com", "X-Title": "DFSRiches Big Picture"},
    )


def huggingface():
    from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

    model = os.environ.get("BIG_PICTURE_MODEL") or "meta-llama/Llama-3.1-8B-Instruct"
    endpoint = HuggingFaceEndpoint(
        repo_id=model, task="conversational", provider=os.environ.get("BIG_PICTURE_PROVIDER") or "auto",
        max_new_tokens=MAX_TOKENS, temperature=0.2, timeout=240, huggingfacehub_api_token=os.environ.get("HF_TOKEN"))
    return ChatHuggingFace(llm=endpoint, model_id=model)


def local_llama():
    """Llama on this machine's CPU through llama.cpp, wrapped as a LangChain Runnable."""
    from huggingface_hub import hf_hub_download
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda
    from llama_cpp import Llama

    path = hf_hub_download(os.environ.get("LOCAL_GGUF_REPO") or LOCAL_REPO, os.environ.get("LOCAL_GGUF_FILE") or LOCAL_FILE)
    llm = Llama(model_path=path, n_ctx=int(os.environ.get("LOCAL_CTX", "16384")), n_threads=os.cpu_count() or 4, verbose=False)
    roles = {"system": "system", "ai": "assistant", "human": "user"}

    def chat(messages) -> AIMessage:
        if hasattr(messages, "to_messages"):          # a ChatPromptValue from a LangChain prompt
            messages = messages.to_messages()
        msgs = [{"role": roles.get(getattr(m, "type", "human"), "user"), "content": str(m.content)} for m in messages]
        r = llm.create_chat_completion(messages=msgs, max_tokens=MAX_TOKENS, temperature=0.2)
        u = r.get("usage") or {}
        return AIMessage(content=r["choices"][0]["message"]["content"] or "",
                         usage_metadata={"input_tokens": u.get("prompt_tokens", 0), "output_tokens": u.get("completion_tokens", 0),
                                         "total_tokens": u.get("total_tokens", 0)})

    return RunnableLambda(chat)


def providers() -> list[tuple[str, Any, bool]]:
    """(label, factory, local) in the order they're tried."""
    out: list[tuple[str, Any, bool]] = []
    if os.environ.get("OPENROUTER_API_KEY"):
        for m in (os.environ.get("OPENROUTER_MODELS") or OPENROUTER_DEFAULT).split(","):
            if m.strip():
                out.append((f"{m.strip()} via OpenRouter (free)", lambda m=m.strip(): openrouter(m), False))
    if os.environ.get("BIG_PICTURE_USE_HF") == "1" and os.environ.get("HF_TOKEN"):
        out.append(("Hugging Face Inference Providers", huggingface, False))
    if os.environ.get("BIG_PICTURE_LOCAL", "1") != "0":
        out.append(("Llama 3.2 3B on the GitHub runner (llama.cpp)", local_llama, True))
    return out


# ------------------------------------------------------------------ the chain
class ProviderChain:
    """Invoke the first provider that works; one that fails is skipped for the rest of the run."""

    def __init__(self, entries: list[tuple[str, Any, bool]] | None = None):
        self.entries = entries if entries is not None else providers()
        self.index = 0
        self._models: dict[int, Any] = {}
        self.used: list[str] = []
        self.failures: list[str] = []

    @property
    def label(self) -> str | None:
        return self.entries[self.index][0] if self.index < len(self.entries) else None

    @property
    def local(self) -> bool:
        return self.index < len(self.entries) and self.entries[self.index][2]

    def _model(self):
        if self.index not in self._models:
            self._models[self.index] = self.entries[self.index][1]()
        return self._models[self.index]

    def invoke(self, messages, **kwargs):
        while self.index < len(self.entries):
            label = self.entries[self.index][0]
            try:
                resp = self._model().invoke(messages, **kwargs)
                if not (getattr(resp, "content", None) or "").strip():
                    raise RuntimeError("empty response")
                if label not in self.used:
                    self.used.append(label)
                return resp
            except Exception as exc:
                # The provider's error (rate limit, daily cap, outage) -- never the prompt.
                self.failures.append(f"{label}: {type(exc).__name__}: {str(exc)[:160]}")
                log.warning("model provider failed, trying the next: %s", self.failures[-1])
                self.index += 1
        raise RuntimeError("every language model provider failed: " + " | ".join(self.failures))

    def probe(self) -> None:
        """One tiny request so a capped or down free tier is skipped before the big prompts are built."""
        from langchain_core.messages import HumanMessage
        while self.index < len(self.entries) and not self.local:
            label = self.entries[self.index][0]
            try:
                resp = self._model().invoke([HumanMessage(content="Reply with OK.")])
                if (getattr(resp, "content", None) or "").strip():
                    return
                raise RuntimeError("empty response")
            except Exception as exc:
                self.failures.append(f"{label}: {type(exc).__name__}: {str(exc)[:160]}")
                log.warning("model provider unavailable, trying the next: %s", self.failures[-1])
                self.index += 1

    def runnable(self):
        """The chain as a LangChain Runnable, for prompt | model | parser pipelines."""
        from langchain_core.runnables import RunnableLambda
        return RunnableLambda(lambda messages: self.invoke(messages))
