"""Synthetic Hospital Lookup Service for AdmitSense (Milestone M6-B).

Provides directory search over dated, versioned synthetic hospital datasets with:
- Stable record IDs and dataset metadata (version and as-of date).
- Explicit identification of records as synthetic demonstration data.
- Strict handling of missing inputs, no matches, and ambiguous matches without
  silently picking an uncertain match.
- Clear separation of hospital directory references from PDF page citations.
- Invariant enforcement: directory records NEVER infer insurer network empanelment,
  cashless eligibility, or claim pre-authorization.
"""

from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Any

from admitsense.schemas import (
    HospitalLookupResult,
    HospitalMatchStatus,
    HospitalRecordReference,
)


def _find_default_dataset_path() -> Path | None:
    """Locates the default synthetic hospital dataset path."""
    candidates = [
        Path("data/hospitals/synthetic_hospitals.json"),
        Path("tests/fixtures/synthetic/hospitals_synthetic_v2026.json"),
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


class HospitalLookupService:
    """Service for searching dated synthetic hospital directory records."""

    def __init__(
        self,
        dataset_path: Path | str | None = None,
        dataset_dict: dict[str, Any] | None = None,
    ) -> None:
        """Initializes the lookup service from a JSON file path or in-memory dictionary."""
        self._records: list[HospitalRecordReference] = []
        self._record_map: dict[str, HospitalRecordReference] = {}
        self.dataset_version: str = "v2026.1"
        self.dataset_date: date = date(2026, 10, 1)
        self.disclaimer: str = (
            "SYNTHETIC DEMONSTRATION DATASET. Not indicative of real network agreements or claim approval."
        )

        if dataset_dict is not None:
            self._load_from_dict(dataset_dict)
        else:
            resolved_path = Path(dataset_path) if dataset_path else _find_default_dataset_path()
            if resolved_path and resolved_path.is_file():
                self._load_from_path(resolved_path)
            else:
                # Fallback to embedded default synthetic dataset
                from admitsense.documents.synthetic import build_synthetic_hospital_json
                self._load_from_dict(build_synthetic_hospital_json())

    def _load_from_path(self, path: Path) -> None:
        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
        except Exception as e:
            raise ValueError(f"Failed to load synthetic hospital dataset from '{path}': {e}") from e
        self._load_from_dict(data)

    def _load_from_dict(self, data: dict[str, Any]) -> None:
        if not isinstance(data, dict):
            raise ValueError("Hospital dataset must be a JSON object.")

        if "dataset_version" not in data or not str(data["dataset_version"]).strip():
            raise ValueError("Hospital dataset missing required 'dataset_version' metadata.")
        self.dataset_version = str(data["dataset_version"]).strip()

        if "dataset_date" not in data:
            raise ValueError("Hospital dataset missing required 'dataset_date' metadata.")
        try:
            if isinstance(data["dataset_date"], date):
                self.dataset_date = data["dataset_date"]
            else:
                self.dataset_date = date.fromisoformat(str(data["dataset_date"]).strip())
        except Exception as e:
            raise ValueError(f"Invalid 'dataset_date' format in hospital dataset: {e}") from e

        if "disclaimer" in data and data["disclaimer"]:
            self.disclaimer = str(data["disclaimer"]).strip()

        raw_hospitals = data.get("hospitals", [])
        if not isinstance(raw_hospitals, list):
            raise ValueError("Hospital dataset 'hospitals' field must be a list.")

        self._records = []
        self._record_map = {}

        for idx, item in enumerate(raw_hospitals):
            if not isinstance(item, dict):
                raise ValueError(f"Hospital record at index {idx} must be a dictionary.")
            if "record_id" not in item or not str(item["record_id"]).strip():
                raise ValueError(f"Hospital record at index {idx} missing required 'record_id'.")
            if "hospital_name" not in item or not str(item["hospital_name"]).strip():
                raise ValueError(f"Hospital record at index {idx} missing required 'hospital_name'.")
            if "city" not in item or not str(item["city"]).strip():
                raise ValueError(f"Hospital record at index {idx} missing required 'city'.")

            rec_date = (
                date.fromisoformat(str(item["dataset_date"]).strip())
                if "dataset_date" in item and item["dataset_date"]
                else self.dataset_date
            )

            record = HospitalRecordReference(
                record_id=str(item["record_id"]).strip(),
                dataset_version=str(item.get("dataset_version", self.dataset_version)).strip(),
                dataset_date=rec_date,
                hospital_name=str(item["hospital_name"]).strip(),
                city=str(item["city"]).strip(),
                network_tier=item.get("network_tier", "unspecified"),
                tpa_desk_contact=item.get("tpa_desk_contact"),
                is_synthetic=True,
                limitations=list(item.get("limitations", [
                    "Synthetic hospital data for demonstration only.",
                    "Does not establish current insurer network agreement or cashless guarantee.",
                ])),
            )
            self._records.append(record)
            self._record_map[record.record_id] = record

    def list_hospitals(self) -> list[HospitalRecordReference]:
        """Returns all hospital records in the dataset."""
        return list(self._records)

    def get_hospital_by_id(self, record_id: str) -> HospitalRecordReference | None:
        """Retrieves a hospital record by its stable synthetic ID."""
        return self._record_map.get(record_id.strip())

    def lookup(
        self,
        hospital_name: str | None,
        city: str | None = None,
    ) -> HospitalLookupResult:
        """Searches the synthetic hospital dataset for matching facilities.

        - If hospital_name is empty or None: returns 'missing_input'.
        - If an exact name match exists: returns 'exact_match'.
        - If multiple potential facilities match: returns 'ambiguous_match' without
          silently selecting an uncertain candidate.
        - If no records match: returns 'no_match'.
        """
        if not hospital_name or not hospital_name.strip():
            return HospitalLookupResult(
                status="missing_input",
                query=None,
                hospital=None,
                candidate_matches=[],
                explanation="Hospital name was not provided. Cannot perform hospital directory lookup.",
                is_synthetic=True,
            )

        query = hospital_name.strip()
        norm_q = " ".join(query.lower().split())
        norm_city = " ".join(city.strip().lower().split()) if city and city.strip() else None

        # 1. Exact Name Matching (case-insensitive)
        exact_matches = [
            h for h in self._records
            if " ".join(h.hospital_name.lower().split()) == norm_q
        ]
        if norm_city and len(exact_matches) > 1:
            city_filtered = [h for h in exact_matches if " ".join(h.city.lower().split()) == norm_city]
            if city_filtered:
                exact_matches = city_filtered

        if len(exact_matches) == 1:
            match = exact_matches[0]
            return HospitalLookupResult(
                status="exact_match",
                query=query,
                hospital=match,
                candidate_matches=[match],
                explanation=(
                    f"Exact match found: '{match.hospital_name}' ({match.record_id}) "
                    f"in synthetic dataset {match.dataset_version} ({match.dataset_date})."
                ),
                is_synthetic=True,
            )
        elif len(exact_matches) > 1:
            return HospitalLookupResult(
                status="ambiguous_match",
                query=query,
                hospital=None,
                candidate_matches=exact_matches,
                explanation=(
                    f"Ambiguous exact hospital query '{query}' matched {len(exact_matches)} facilities: "
                    f"{', '.join(h.hospital_name + ' (' + h.city + ')' for h in exact_matches)}. "
                    "City disambiguation required; no uncertain match silently selected."
                ),
                is_synthetic=True,
            )

        # 2. Substring & Token-based Matching
        candidate_matches: list[HospitalRecordReference] = []
        for h in self._records:
            h_norm = " ".join(h.hospital_name.lower().split())
            if norm_q in h_norm or all(token in h_norm for token in norm_q.split()):
                if norm_city:
                    if norm_city in " ".join(h.city.lower().split()):
                        candidate_matches.append(h)
                else:
                    candidate_matches.append(h)

        if len(candidate_matches) == 1:
            match = candidate_matches[0]
            return HospitalLookupResult(
                status="exact_match",
                query=query,
                hospital=match,
                candidate_matches=[match],
                explanation=(
                    f"Unique candidate match: '{match.hospital_name}' ({match.record_id}) "
                    f"in synthetic dataset {match.dataset_version} ({match.dataset_date})."
                ),
                is_synthetic=True,
            )
        elif len(candidate_matches) > 1:
            return HospitalLookupResult(
                status="ambiguous_match",
                query=query,
                hospital=None,
                candidate_matches=candidate_matches,
                explanation=(
                    f"Ambiguous hospital query '{query}' matched {len(candidate_matches)} facilities: "
                    f"{', '.join(h.hospital_name for h in candidate_matches)}. "
                    "Disambiguation required; no uncertain match silently selected."
                ),
                is_synthetic=True,
            )

        # 3. No match found
        return HospitalLookupResult(
            status="no_match",
            query=query,
            hospital=None,
            candidate_matches=[],
            explanation=(
                f"No matching hospital record found for query '{query}' in synthetic hospital dataset "
                f"{self.dataset_version} (as of {self.dataset_date})."
            ),
            is_synthetic=True,
        )
