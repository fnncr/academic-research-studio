"""P7 v2 is a revision-scoped editorial preview, not an AI-origin detector."""
from uuid import uuid4

from app.editorial_review_v2 import inspect
from app.manuscript_schema import ManuscriptDocument
from test_manuscripts import manuscript, save  # noqa: F401 - postgres fixture


PHRASE = ("Цифровые сервисы ускоряют выполнение отдельных операций, "
          "однако общий экономический результат зависит от многих других условий.")
ALT = ("В исследовании рассматриваются различные институты платежного рынка, "
       "а также доступность инфраструктуры и ограничения используемых данных.")


def doc(*blocks):
    return ManuscriptDocument.model_validate({
        "schema_version": "1",
        "blocks": [{"type": kind, "id": str(uuid4()), "text": value}
                   for kind, value in blocks],
    })


def test_repeated_distinct_paragraphs_create_exact_utf16_candidate():
    original = "🧪 " + PHRASE
    manuscript = doc(("paragraph", original), ("paragraph", PHRASE))
    result = inspect(manuscript, uuid4())
    assert len(result["findings"]) == 1
    finding = result["findings"][0]
    assert finding["criterion_id"] == "35"
    assert finding["quote"] == PHRASE
    assert finding["start"] == 0
    assert finding["end"] == len(PHRASE.encode("utf-16-le")) // 2
    assert finding["related_block_id"] == str(manuscript.blocks[0].id)
    assert next(c for c in result["coverage"] if c["criterion_id"] == "43")["status"] == "insufficient_data"


def test_utf16_emoji_offset_in_repeated_second_paragraph():
    manuscript = doc(("paragraph", PHRASE), ("paragraph", "🧪 " + PHRASE))
    result = inspect(manuscript, uuid4())
    assert result["findings"][0]["start"] == 3
    assert result["findings"][0]["quote"] == PHRASE


def test_long_distance_repeat_is_other_rule_and_original_preserved():
    manuscript = doc(("paragraph", PHRASE),
                     ("paragraph", ALT), ("paragraph", ALT + " Дополнительная проверка необходима."),
                     ("paragraph", ALT), ("paragraph", ALT + " Отдельный факт пока не установлен."),
                     ("paragraph", PHRASE))
    result = inspect(manuscript, uuid4())
    assert any(f["criterion_id"] == "42" and f["quote"] == PHRASE for f in result["findings"])
    assert manuscript.blocks[0].text == PHRASE


def test_quotes_formulas_and_short_conventional_sentences_are_not_flagged():
    manuscript = ManuscriptDocument.model_validate({
        "schema_version": "2",
        "blocks": [
            {"id": str(uuid4()), "type": "quote", "text": PHRASE},
            {"id": str(uuid4()), "type": "formula", "text": PHRASE},
            {"id": str(uuid4()), "type": "paragraph", "text": "Это определение рынка."},
            {"id": str(uuid4()), "type": "paragraph", "text": ALT},
        ],
    })
    result = inspect(manuscript, uuid4())
    assert not result["findings"]
    assert next(c for c in result["coverage"] if c["criterion_id"] == "35")["status"] == "insufficient_data"


def test_review_scoped_to_saved_revision_and_owner(monkeypatch, manuscript):
    client, project_id, _ = manuscript
    saved = save(client, project_id, {
        "schema_version": "1",
        "blocks": [{"id": str(uuid4()), "type": "paragraph", "text": PHRASE},
                   {"id": str(uuid4()), "type": "paragraph", "text": PHRASE}]
    }).json()
    url = f"/api/projects/{project_id}/editorial/revisions/{saved['id']}/preview"
    assert client.get(url).status_code == 503  # No configured owner secret.
    monkeypatch.setenv("MODEL_OWNER_TOKEN", "owner-" + "s" * 40)
    assert client.get(url).status_code == 401
    headers = {"Authorization": "Bearer owner-" + "s" * 40}
    response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["revision_id"] == saved["id"]
    assert len(data["findings"]) == 1
    assert client.get(f"/api/projects/{uuid4()}/editorial/revisions/{saved['id']}/preview", headers=headers).status_code == 404
    assert client.get(f"/api/projects/{project_id}/editorial/revisions/{uuid4()}/preview", headers=headers).status_code == 404
    assert client.get(f"/api/projects/{project_id}/manuscript/revisions/{saved['id']}").json()["document"] == saved["document"]
