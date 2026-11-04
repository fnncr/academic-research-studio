# P6.1 — fallback-поставка и матрица приёмки

Основание: main 513dd2e (PR #23–24 включены). Первая часть: PR #25,
вторая — scientific evaluation / UI / acceptance preparation. Новая реальная
модель **не подключена**, P6.1 real integration остаётся blocked.

Документированный ID: gpt-6.1-sol. Endpoints /v1/responses и /v1/chat/completions
описаны в официальном каталоге. Доступ этого приложения и полный биллинговый
контракт не подтверждены. Реальные inference/token-count calls: **0**.
[Проверка совместимости и источники](p6-1-model-compatibility.md).

| Область | Поставка | Ограничение |
| --- | --- | --- |
| Model compatibility | read-only unavailable_models, ID/context/efforts/modes | Не executable provider; нет Sol quote или dispatch |
| Режимы | Standard Draft/Deep Academic Writing/Complex Research Review как отключённые предложения | Нет работающего reasoning selector; mock остаётся локальным шаблоном |
| Бюджет | UI различает приблизительную оценку (не рассчитана), reserve, учтённый расход и ambiguity | Нет выдуманной оценки/сверки инвойса; PR #22–23 финансовый контракт сохранён |
| Контекст | Прежний scoped context, Evidence/версии/точные цитаты и consent | Текущий запрос без section включает всю ограниченную рукопись явно в preview; будущий Sol adapter должен требовать section для section-task |
| Генерация | Три реальные локальные mock-проверки научных сценариев | Синтез/качество Sol не измерены |
| Рецензия | Существующий отдельный SemanticReview/API | Новый Sol reviewer и UI запуска review не реализованы; A03/A05 аудита открыты |
| Рукопись/DOCX | Прежнее атомарное append acceptance, rich-object/export regression | Microsoft Word/официальный шаблон не проверялись заново |
| Live | Исполняемый local preparation CLI; по умолчанию только blocked report | Ни один флаг CLI не разрешает отправку; нужен отдельный проверенный adapter |

## Научный evaluation suite

`backend/app/scientific_evaluation.py` содержит три явно синтетических случая:
экономическая теория (спрос/издержки), менеджмент (централизация/автономия),
финтех (автоматизация/операционные риски). Каждый имеет RU/EN supports,
contradicts, limits, исходные фрагменты и экспертные вопросы. Нет вымышленных
DOI/авторов/страниц: metadata только помеченные synthetic titles/languages.

`test_scientific_evaluation.py` создаёт настоящие SourceVersion/Evidence/Claim/
ManuscriptRevision через API в одноразовых PostgreSQL schemas; запускает mock
через существующий queue, проверяет exact citations и полный набор relations.
Артефакты [evaluation](validation/p6-1-evaluation/) сохраняют Proposal/отчёт и
раздельные статусы:
- Structural validity: passed для local mock.
- Scientific adequacy: requires_expert_review.
- Writing quality: requires_expert_review.

Оценивать отдельно полноту Evidence, корректность цитирования/смысла, вымыслы,
силу выводов, сравнение, противоположные позиции, стиль и полезность. Для каждого
замечания указать фрагмент и Evidence. Не усреднять в процент научной достоверности.
Проверки свободного prose остаются ограниченными, как в независимом аудите.
Повторяемость означает фиксированные тексты сценариев/инварианты; UUID новых
записей различаются. Сохранённый результат не регенерируется при чтении.

Из backend для повторения (только тестовая PostgreSQL):

```sh
TEST_DATABASE_URL=postgresql+psycopg://studio@127.0.0.1:55432/studio_test \
P61_EVALUATION_ARTIFACT_DIR=/tmp/p61-evaluation \
../.venv/bin/python -m pytest -q tests/test_scientific_evaluation.py
```

## Исполняемая подготовка live

Без ключа, БД и сети:

```sh
../.venv/bin/python -m app.scientific_evaluation --output /tmp/p61-live.json
```

Получается blocked report, никаких записей или HTTP-вызовов.
С `--prepare` и DATABASE_URL **одноразовой мигрированной БД** создаются три
синтетических проекта/версии, сохраняются реальные UUID и prepared_mock_task.
Подготовщик не делает enqueue, preview у провайдера или token counting. Не
менять model в полученном JSON и не считать это готовым Sol request.
Эта проверка подготовщика также входит в тесты.

До реального запуска: согласовать полный Responses billing/cache-write contract,
модель/tier/region, отдельный application key, штатную сеть, цену/предельный резерв,
передачу конкретного context и request UUID. Включать один writing вызов только
после нового preview и согласия; SemanticReview — ещё одно отдельное решение.
Нынешняя стоимость/резерв Sol неизвестны и равны null; максимальный бюджет нельзя
утвердить из ставки старой модели. [Существующий live-протокол](validation/p6-live-acceptance.md)
описывает общую дисциплину, но его числа относятся исключительно к старой модели.
При unknown расходе удержать резерв и остановиться; не создавать второй UUID.

## Проверки этой поставки

Окончательный полный локальный backend: **332 passed**, zero skips, 57.95 s,
включая тест --prepare. Отдельный evaluation suite: **5 passed**.
Frontend: **53 passed**, TypeScript/Vite build passed. Полный backend включает
миграции upgrade/downgrade/re-upgrade/check, billing faults, queue concurrency,
consent, injection/UUID/scopes, cancellation/timeouts/restarts, цитаты и DOCX.
Отдельного нового Sol HTTP adapter нет: успешные/ошибочные Responses, reasoning
и cache-write settlement **не объявляются протестированными**. Старые 401/429/5xx/
usage/refusal tests относятся к старому адаптеру. Нет новых dependencies/migrations.

Новый browser smoke использует Chromium и настоящие API/worker/PostgreSQL:
согласие с клавиатуры, один enqueue, reload/UUID, отдельный mock review через API,
accept, DOCX download, restore без rebasing. Результат записан в журнал проверки.

Перед P7 сохраняются рекомендации p7-readiness.md: локальные формальные правила
независимы от live P6, реестр 34 критериев не менялся. Sol integration, экспертная
приёмка, provenance в редакторе и слепая смысловая рецензия остаются открытыми.

## Тарифная справка для будущего контракта

Официальный pricing на дату проверки: Standard input/output $2/$10 за миллион,
cached input $0.10, 30m/12h cache write $2.50/$5. Для входа свыше 272K действует
надбавка на весь запрос; fast/ultrafast и regional processing имеют дополнительные
множители. Эти справочные ставки не являются реализованной Sol quote и не
подтверждают исчерпывающую верхнюю границу. Cache write usage/control и доступ
аккаунта остаются блокерами. [Pricing](https://developers.openai.com/api/docs/pricing).

PR: [25](https://github.com/fnncr/academic-research-studio/pull/25) и зависимый
[26](https://github.com/fnncr/academic-research-studio/pull/26). Не объединены агентом.
