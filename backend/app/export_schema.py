"""Explicit export inputs. No institutional-standard or automatic truth claims."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator
from app.source_schema import Strict

Text = Annotated[str, StringConstraints(strict=True, max_length=500)]
Size = Annotated[float, Field(strict=True, ge=8, le=24)]
Margin = Annotated[float, Field(strict=True, ge=0.5, le=5)]


class ExportProfile(Strict):
    name: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=100)]
    paper: Literal['A4'] = 'A4'
    font: Literal['Times New Roman', 'Arial', 'Calibri'] = 'Times New Roman'
    font_size: Size = 14
    line_spacing: Annotated[float, Field(strict=True, ge=1, le=3)] = 1.5
    alignment: Literal['justify', 'left'] = 'justify'
    first_line_cm: Annotated[float, Field(strict=True, ge=0, le=3)] = 1.25
    margin_top_cm: Margin = 2
    margin_bottom_cm: Margin = 2
    margin_left_cm: Margin = 3
    margin_right_cm: Margin = 1.5
    paragraph_after_pt: Annotated[float, Field(strict=True, ge=0, le=24)] = 0
    header: Text = ''
    footer: Text = ''
    page_numbers: Annotated[bool, Field(strict=True)] = True
    toc: Annotated[bool, Field(strict=True)] = True
    number_tables: Annotated[bool, Field(strict=True)] = True

    @model_validator(mode='after')
    def usable_page(self):
        if self.margin_left_cm + self.margin_right_cm > 12:
            raise ValueError('Page too narrow')
        return self


class TitlePage(Strict):
    enabled: Annotated[bool, Field(strict=True)] = True
    university: Text = ''
    department: Text = ''
    discipline: Text = ''
    topic: Text = ''
    author: Text = ''
    group: Text = ''
    teacher: Text = ''
    city: Text = ''
    year: Annotated[int, Field(strict=True, ge=1000, le=2200)] | None = None


class ExportRequest(Strict):
    manuscript_revision_id: UUID
    plan_revision_id: UUID | None
    without_plan: Annotated[bool, Field(strict=True)] = False
    profile: ExportProfile
    title_page: TitlePage
    citation_style: Literal['numeric-v1']
    preflight_token: Annotated[str, StringConstraints(strict=True, pattern=r'^[a-f0-9]{64}$')] | None = None
