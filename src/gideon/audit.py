"""Audit trail + running cost tally (Tier 6).

A plain append-only JSONL log of what Gideon did and why — tools run, confirmations asked,
errors, heartbeat surfaces — plus a token/cost tally so a runaway loop is visible immediately.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .config import AUDIT_PATH, Config


class Audit:
    def __init__(self, config: Config) -> None:
        self._config = config
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)

    def _append(self, record: dict[str, Any]) -> None:
        record["ts"] = datetime.now(timezone.utc).isoformat()
        with AUDIT_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def log(self, event: str, **fields: Any) -> None:
        self._append({"event": event, **fields})

    def log_usage(self, input_tokens: int, output_tokens: int) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self._append(
            {
                "event": "usage",
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "session_cost_usd": round(self.session_cost_usd, 4),
            }
        )

    @property
    def session_cost_usd(self) -> float:
        cfg = self._config
        return (
            self.total_input_tokens / 1_000_000 * cfg.input_price_per_mtok
            + self.total_output_tokens / 1_000_000 * cfg.output_price_per_mtok
        )
