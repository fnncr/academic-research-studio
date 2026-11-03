"""Strict, versioned specification data. Does not evaluate uploaded documents."""
import json
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(min_length=1, pattern=r'\S')]
CriterionId = Annotated[str, StringConstraints(pattern=r'^(0[1-9]|[12][0-9]|3[0-4])$')]
Version = Annotated[str, StringConstraints(pattern=r'^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$')]
EXPECTED_IDS = [f'{number:02}' for number in range(1, 35)]
REGISTRY_PATH = Path(__file__).resolve().parent / 'data' / 'editorial-criteria.v1.json'


class StrictModel(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)


class Criterion(StrictModel):
    id: CriterionId
    name: Text
    # Required key, nullable only when the source genuinely has no description.
    description: Text | None
    description_status: Literal['missing_in_source', 'provided']
    signals: Text
    review_action: Text
    exceptions: Text

    @model_validator(mode='after')
    def description_provenance(self) -> Self:
        if (self.description is None) != (self.description_status == 'missing_in_source'):
            raise ValueError('description and description_status disagree')
        return self


class EditorialRegistry(StrictModel):
    schema_version: Literal['1']
    registry_version: Version
    source: Literal['docs/editorial-criteria.md']
    source_sha256: Annotated[str, StringConstraints(pattern=r'^[a-f0-9]{64}$')]
    evaluation_rules: Text
    priorities: Annotated[list[Text], Field(min_length=5, max_length=5)]
    criteria: Annotated[list[Criterion], Field(min_length=34, max_length=34)]

    @model_validator(mode='after')
    def complete_ordered_ids(self) -> Self:
        if [criterion.id for criterion in self.criteria] != EXPECTED_IDS:
            raise ValueError('criteria must contain exactly IDs 01–34, once each, in order')
        return self


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError(f'Invalid JSON constant: {value}')


def load_registry(path: Path = REGISTRY_PATH) -> EditorialRegistry:
    """Reject ambiguous JSON and unsupported schema versions, without coercion."""
    data = json.loads(path.read_text(encoding='utf-8'),
                      object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    return EditorialRegistry.model_validate(data)


if __name__ == '__main__':
    registry = load_registry()
    missing = sum(item.description is None for item in registry.criteria)
    print(f'Registry {registry.registry_version}: {len(registry.criteria)} criteria validated; '
          f'{missing} descriptions missing in source.')
