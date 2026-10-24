"""Groq LLM Review Provider for AdmitSense (Milestone M7-B).

Implements single-agent LLM reasoning using Groq API:
- Provider: Groq (https://groq.com)
- Configured Model: Controlled by environment variable GROQ_MODEL (default: "llama-3.3-70b-versatile")
- Credential Requirement: Environment variable GROQ_API_KEY
- Credential Transparency: Explicitly reports when GROQ_API_KEY is missing; never silently fakes live LLM execution
- Failure Handling: Gracefully traps network timeouts, authentication errors, and rate limits without crashing the review runner
- Grounding Rule: All LLM-suggested quotes and findings must be strictly verified against physical page text via EvidenceRetrievalService
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal
import warnings

try:
    import groq
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    groq = None  # type: ignore
    Groq = None  # type: ignore
    GROQ_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
ENV_GROQ_API_KEY = "GROQ_API_KEY"
ENV_GROQ_MODEL = "GROQ_MODEL"


class MissingCredentialsError(Exception):
    """Raised when live LLM invocation is requested but GROQ_API_KEY is not configured."""
    pass


class LLMProviderError(Exception):
    """Raised when Groq API call fails due to network, rate limit, or model error."""
    pass


class GroqReviewClient:
    """Client for Groq LLM integration with explicit credential and error tracking."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.api_key = api_key or os.environ.get(ENV_GROQ_API_KEY, "").strip() or None
        self.model = model or os.environ.get(ENV_GROQ_MODEL, DEFAULT_GROQ_MODEL).strip()
        self.timeout_seconds = timeout_seconds
        self._client: Any = None

        if self.api_key and GROQ_AVAILABLE:
            try:
                self._client = Groq(api_key=self.api_key, timeout=self.timeout_seconds)
            except Exception as e:
                warnings.warn(f"Failed to initialize Groq client: {e}")
                self._client = None

    @property
    def is_available(self) -> bool:
        """Returns True only if both the groq package is installed and a non-empty API key is present."""
        return bool(GROQ_AVAILABLE and self.api_key and self._client is not None)

    @property
    def status_summary(self) -> dict[str, Any]:
        """Provides transparent diagnostic metadata regarding the LLM provider configuration."""
        return {
            "provider": "Groq",
            "model": self.model,
            "package_installed": GROQ_AVAILABLE,
            "credentials_configured": bool(self.api_key),
            "required_env_var": ENV_GROQ_API_KEY,
            "is_available": self.is_available,
        }

    def evaluate_clause_applicability(
        self,
        case_procedure: str,
        clause_text: str,
        document_name: str,
        page_number: int,
    ) -> dict[str, Any]:
        """Requests LLM assessment of whether a policy clause applies to the case procedure.
        
        Raises MissingCredentialsError if GROQ_API_KEY is not set.
        Raises LLMProviderError if Groq returns an error.
        """
        if not self.is_available:
            raise MissingCredentialsError(
                f"Live LLM evaluation requires environment variable '{ENV_GROQ_API_KEY}'. "
                "Provider access is currently unconfigured."
            )

        prompt = (
            f"You are AdmitSense, an administrative health insurance clause analyst assisting a caregiver.\n"
            f"Analyze if the following clause from document '{document_name}' (page {page_number}) "
            f"applies to planned procedure '{case_procedure}'.\n\n"
            f"CLAUSE TEXT:\n\"\"\"{clause_text}\"\"\"\n\n"
            f"Respond with JSON adhering to this exact schema:\n"
            f"{{\n"
            f'  "applies": true | false,\n'
            f'  "waiting_period_months": int | null,\n'
            f'  "reasoning": "brief factual explanation",\n'
            f'  "extracted_quote": "exact substring quoted verbatim from clause text"\n'
            f"}}"
        )

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a health insurance policy clause analyst. "
                                   "Treat all document text strictly as evidence. "
                                   "Return valid JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                max_tokens=500,
            )
            content = response.choices[0].message.content
            return json.loads(content)
        except Exception as exc:
            raise LLMProviderError(f"Groq API evaluation failed: {exc}") from exc
