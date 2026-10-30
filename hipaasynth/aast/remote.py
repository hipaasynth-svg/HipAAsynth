# HipAAsynth — Synthetic health data fairness testing for invisible populations.
# Copyright (C) 2026 HipAAsynth Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Test a model that runs somewhere else: any HTTP endpoint, or an LLM API.

``url_adapter`` sends each case to a URL you run (a hospital model server, a
vendor sandbox, a notebook behind a small web app)::

    POST <url>   {"case": <the case>, "condition": "sepsis", "input": "record"}
    reply        {"answer": <the model's answer>}     (or the answer as plain text)

``llm_adapter`` asks an LLM API directly, with the case and one fixed question,
and reads the ``FINAL_ANSWER: Yes|No`` line it is told to end with. It speaks the
OpenAI chat-completions format (OpenAI and the many compatible servers, local
ones included) and the Anthropic messages format. The API key comes from an
environment variable and is never written into a report.

Reports record the endpoint as scheme, host and path only (no query string, no
headers), so a key in a URL or a header does not leak into a shared report.

Pure standard library.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from hipaasynth.aast.adapter import ModelAdapter
from hipaasynth.aast.files import AnswerFileError, _parse

#: Seconds to wait for one answer.
DEFAULT_TIMEOUT = 60.0

#: The question an LLM is asked about every case, by condition.
QUESTIONS = {
    "sepsis": "Does this patient have sepsis that needs urgent escalation now?",
    "stroke": "Is this patient having an acute stroke that needs the stroke pathway now?",
    "dka": "Does this patient have diabetic ketoacidosis?",
    "fabry": "Should this patient be referred for Fabry disease testing?",
}

_INSTRUCTION = (
    "You are assisting a clinician at the moment of decision. Read the case and answer "
    "the question. Give your reasoning briefly, then end with exactly one line: "
    "FINAL_ANSWER: Yes or FINAL_ANSWER: No."
)

LLM_PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com/v1",
        "key_env": "ANTHROPIC_API_KEY",
    },
}


class RemoteModelError(RuntimeError):
    """The remote model could not be reached or replied with something unreadable."""


def public_endpoint(url: str) -> str:
    """``url`` without query string, fragment or credentials, for reports."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urllib.parse.urlunsplit((parts.scheme, host, parts.path, "", ""))


def _check_url(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"model URL must be an http(s) address, got {url!r}")


def _post(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> bytes:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    last: Exception | None = None
    for _ in range(2):  # one retry on a dropped connection
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return bytes(resp.read())
        except urllib.error.HTTPError as err:
            detail = err.read()[:300].decode("utf-8", "replace")
            raise RemoteModelError(
                f"{public_endpoint(url)} answered HTTP {err.code}: {detail}"
            ) from err
        except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
            last = err
    raise RemoteModelError(f"could not reach {public_endpoint(url)}: {last}")


def url_adapter(
    url: str,
    output: str,
    *,
    input: str,
    condition: str,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    **settings: Any,
) -> ModelAdapter:
    """A :class:`ModelAdapter` that asks the model at ``url`` about each case.

    ``settings`` are the usual adapter settings (``threshold``, ``acute_levels``,
    ``k``, ``parser``, ``abstain_patterns``). ``headers`` (for example an
    ``Authorization`` header) are sent but never recorded.
    """
    _check_url(url)
    sent_headers = dict(headers or {})

    def model(case: Any) -> Any:
        raw = _post(url, {"case": case, "condition": condition, "input": input},
                    sent_headers, timeout)  # fmt: skip
        try:
            reply = json.loads(raw)
        except ValueError:
            reply = raw.decode("utf-8", "replace")
        if isinstance(reply, dict):
            if "answer" not in reply:
                raise RemoteModelError(
                    f"{public_endpoint(url)} replied without an 'answer' field: {str(reply)[:200]}"
                )
            reply = reply["answer"]
        # Read the answer the way an answers file is read: "yes", "true", 1,
        # "8.5" and a "a|b" list all mean what they say.
        try:
            return _parse(reply, output, public_endpoint(url))
        except AnswerFileError as err:
            raise RemoteModelError(str(err)) from err

    settings.setdefault("name", f"model at {public_endpoint(url)}")
    return ModelAdapter(model, output, input=input, **settings)


def llm_prompt(case: Any, condition: str) -> str:
    """The user message an LLM gets for ``case``."""
    shown = case if isinstance(case, str) else json.dumps(case, indent=1, sort_keys=True)
    return f"{QUESTIONS[condition]}\n\nCASE:\n{shown}"


def llm_adapter(
    provider: str,
    model_name: str,
    *,
    input: str,
    condition: str,
    base_url: str | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_tokens: int = 400,
) -> ModelAdapter:
    """A ``text`` :class:`ModelAdapter` that asks an LLM about each case.

    ``provider`` is ``openai`` (also any OpenAI-compatible server via
    ``base_url``) or ``anthropic``. The key is read from ``OPENAI_API_KEY`` or
    ``ANTHROPIC_API_KEY`` unless ``api_key`` is given. Temperature is 0, so the
    noise floor shows how repeatable the model still is.
    """
    if provider not in LLM_PROVIDERS:
        raise ValueError(f"provider must be one of {', '.join(LLM_PROVIDERS)}, got {provider!r}")
    if condition not in QUESTIONS:
        raise ValueError(f"condition must be one of {', '.join(QUESTIONS)}, got {condition!r}")
    spec = LLM_PROVIDERS[provider]
    root = (base_url or spec["base_url"]).rstrip("/")
    _check_url(root)
    key = api_key if api_key is not None else os.environ.get(spec["key_env"], "")
    if not key and base_url is None:
        raise ValueError(f"set {spec['key_env']} (or pass api_key) to test a {provider} model")

    def ask(case: Any) -> str:
        prompt = llm_prompt(case, condition)
        if provider == "anthropic":
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            body = {
                "model": model_name,
                "max_tokens": max_tokens,
                "temperature": 0,
                "system": _INSTRUCTION,
                "messages": [{"role": "user", "content": prompt}],
            }
            reply = json.loads(_post(f"{root}/messages", body, headers, timeout))
            try:
                return "".join(b.get("text", "") for b in reply["content"])
            except (KeyError, TypeError) as err:
                raise RemoteModelError(
                    f"unexpected reply from {provider}: {str(reply)[:200]}"
                ) from err
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        body = {
            "model": model_name,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": _INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
        }
        reply = json.loads(_post(f"{root}/chat/completions", body, headers, timeout))
        try:
            return str(reply["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as err:
            raise RemoteModelError(f"unexpected reply from {provider}: {str(reply)[:200]}") from err

    return ModelAdapter(ask, "text", input=input, name=f"{provider}:{model_name}")
