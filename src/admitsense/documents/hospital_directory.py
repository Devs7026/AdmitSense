"""Synthetic Hospital Directory Service and Lookup Protocols (Milestone M6).

Conforms to CONTRACTS.md Section 3.4 and DEC-004:
- Evaluates hospital references against dated synthetic demonstration data.
- Handles matched, no_match, ambiguous_match, and missing_information states.
- Explicitly enforces that synthetic directory records do NOT establish live insurer
  network status, cashless eligibility, or claim authorization.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field

from admitsense.documents.synthetic import build_synthetic_hospital_json
from admitsense.schemas import HospitalRecordReference

HospitalMatchStatus = Literal[
    "matched",
    "no_match",
    "ambiguous_match",
    "missing_information",
]


class HospitalLookupResult(BaseModel):
    """Result of querying the hospital reference dataset."""

    model_config = ConfigDict(extra="forbid")

    status: HospitalMatchStatus
    record: HospitalRecordReference | None = None
    candidates: list[HospitalRecordReference] = Field(default_factory=list)
    query: str | None = None
    dataset_version: str = "v2026.1"
    dataset_date: date = Field(default_factory=lambda: date(2026, 10, 1))
    message: str = ""
    disclaimer: str = (
        "SYNTHETIC DEMONSTRATION DATASET. Not indicative of real network agreements "
        "or claim approval. Does not establish current insurer network agreement or cashless guarantee."
    )
    is_synthetic: bool = True


class HospitalLookupService(Protocol):
    """Protocol for hospital reference lookups."""

    def lookup_hospital(
        self,
        hospital_name: str | None,
        city: str | None = None,
    ) -> HospitalLookupResult:
        """Lookup a hospital record by name and optional city."""
        ...


class LocalSyntheticHospitalDirectory:
    """In-memory directory provider for synthetic hospital dataset."""

    DEFAULT_DISCLAIMER = (
        "SYNTHETIC DEMONSTRATION DATASET. Not indicative of real network agreements "
        "or claim approval. Does not establish current insurer network agreement or cashless guarantee."
    )

    def __init__(self, json_path: Path | str | None = None) -> None:
        self.dataset_version = "v2026.1"
        self.dataset_date = date(2026, 10, 1)
        self.disclaimer = self.DEFAULT_DISCLAIMER
        self.records: list[HospitalRecordReference] = []

        raw_data = None
        if json_path is not None:
            p = Path(json_path)
            if p.is_file():
                raw_data = json.loads(p.read_text(encoding="utf-8"))

        if raw_data is None:
            # Fallback to standard synthetic builder
            raw_data = build_synthetic_hospital_json()

        self._load_dataset(raw_data)

    def _load_dataset(self, data: dict) -> None:
        self.dataset_version = str(data.get("dataset_version", "v2026.1"))
        date_str = data.get("dataset_date", "2026-10-01")
        if isinstance(date_str, str):
            self.dataset_date = date.fromisoformat(date_str)
        elif isinstance(date_str, date):
            self.dataset_date = date_str

        loaded_disclaimer = data.get("disclaimer", self.DEFAULT_DISCLAIMER)
        if "Does not establish current insurer network agreement" not in loaded_disclaimer:
            loaded_disclaimer = f"{loaded_disclaimer} Does not establish current insurer network agreement or cashless guarantee.".strip()
        self.disclaimer = loaded_disclaimer

        self.records = []
        for item in data.get("hospitals", []):
            item_date = item.get("dataset_date", self.dataset_date)
            if isinstance(item_date, str):
                item_date = date.fromisoformat(item_date)

            rec = HospitalRecordReference(
                record_id=item["record_id"],
                dataset_version=item.get("dataset_version", self.dataset_version),
                dataset_date=item_date,
                hospital_name=item["hospital_name"],
                city=item.get("city", "Bengaluru"),
                network_tier=item.get("network_tier", "unspecified"),
                tpa_desk_contact=item.get("tpa_desk_contact"),
                limitations=item.get(
                    "limitations",
                    [
                        "Synthetic hospital data for demonstration only.",
                        "Does not establish current insurer network agreement or cashless guarantee.",
                    ],
                ),
            )
            self.records.append(rec)

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())

    def lookup_hospital(
        self,
        hospital_name: str | None,
        city: str | None = None,
    ) -> HospitalLookupResult:
        """Lookup a hospital against synthetic records.

        Returns:
            - missing_information: hospital_name is None or empty.
            - matched: exactly one distinct record matched.
            - ambiguous_match: query matched multiple hospital facilities.
            - no_match: hospital_name was given but no matching facility was found.
        """
        if not hospital_name or not hospital_name.strip():
            return HospitalLookupResult(
                status="missing_information",
                query=None,
                dataset_version=self.dataset_version,
                dataset_date=self.dataset_date,
                message="Hospital name is not specified in case details.",
                disclaimer=self.disclaimer,
            )

        query = hospital_name.strip()
        norm_query = self._normalize(query)
        norm_city = self._normalize(city) if city and city.strip() else None

        # 1. Filter by city if specified
        scope = self.records
        if norm_city:
            city_filtered = [r for r in scope if self._normalize(r.city) == norm_city]
            if city_filtered:
                scope = city_filtered

        # 2. Exact match
        exact_matches = [
            r for r in scope if self._normalize(r.hospital_name) == norm_query
        ]
        if len(exact_matches) == 1:
            return HospitalLookupResult(
                status="matched",
                record=exact_matches[0],
                query=query,
                dataset_version=self.dataset_version,
                dataset_date=self.dataset_date,
                message=f"Matched record '{exact_matches[0].hospital_name}' in synthetic dataset.",
                disclaimer=self.disclaimer,
            )

        # 3. Substring / Token matching
        partial_matches: list[HospitalRecordReference] = []
        for r in scope:
            norm_r_name = self._normalize(r.hospital_name)
            if norm_query in norm_r_name or norm_r_name in norm_query:
                partial_matches.append(r)
            else:
                # Token overlap check (ignoring generic words)
                generic_words = {"hospital", "clinic", "super", "specialty", "health", "centre", "center"}
                q_tokens = {t for t in norm_query.split() if t not in generic_words}
                r_tokens = {t for t in norm_r_name.split() if t not in generic_words}
                if q_tokens and (q_tokens & r_tokens):
                    partial_matches.append(r)

        if len(partial_matches) == 1:
            return HospitalLookupResult(
                status="matched",
                record=partial_matches[0],
                query=query,
                dataset_version=self.dataset_version,
                dataset_date=self.dataset_date,
                message=f"Matched record '{partial_matches[0].hospital_name}' in synthetic dataset.",
                disclaimer=self.disclaimer,
            )
        elif len(partial_matches) > 1:
            return HospitalLookupResult(
                status="ambiguous_match",
                candidates=partial_matches,
                query=query,
                dataset_version=self.dataset_version,
                dataset_date=self.dataset_date,
                message=(
                    f"Multiple facilities ({len(partial_matches)}) match query '{query}'. "
                    "Please specify the exact facility name."
                ),
                disclaimer=self.disclaimer,
            )

        return HospitalLookupResult(
            status="no_match",
            query=query,
            dataset_version=self.dataset_version,
            dataset_date=self.dataset_date,
            message=f"No record found matching '{query}' in synthetic hospital dataset {self.dataset_version}.",
            disclaimer=self.disclaimer,
        )
