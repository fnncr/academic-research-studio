# Academic Research Studio

Основа приложения для работы с исследовательскими документами: загрузка DOCX и текстовых PDF, извлечение текста, персональные проекты, версии требований, ручной структурный редактор и библиотека источников с версиями метаданных и поиском Crossref/OpenAlex. Редакторская проверка по 34 критериям, научная проверка утверждений и OCR пока не реализованы. Добавлен экспорт сохранённых версий в DOCX (P5).

## Локальный запуск

Требуются Linux, Python 3.12+ и Node.js 22.12+ (проверено с Python 3.12 и Node 24). Для Windows используйте WSL. Ограничения ресурсов обработчика используют Linux `resource`.

Из корня репозитория:

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd backend
../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Во втором терминале, из корня:

```bash
cd frontend
npm ci
npm run dev
```

Откройте адрес, который выводит Vite (обычно порт 5173). Vite передаёт `/api` локальному backend. Для извлечения текста секреты и база данных не нужны; файлы и результаты извлечения не сохраняются. Раздел «Проекты» использует PostgreSQL для проектов и истории требований преподавателя. Настройка DATABASE_URL, Compose и миграций описана в [инструкции P1a](docs/projects.md).

## Проверки

Из корня:

```bash
(cd backend && ../.venv/bin/python -m pytest -q)
(cd frontend && npm test && npm run build)
```

Проверка работающего API:

```bash
curl --fail http://127.0.0.1:8000/api/health
curl --fail --data-binary @document.docx -H 'Content-Type: application/octet-stream' \
  'http://127.0.0.1:8000/api/documents/extract?filename=document.docx'
```

POST принимает сам файл в теле, не multipart. Ответ содержит `format`, `text`, `chunks` (текст и номер страницы PDF), `pages` (null для DOCX). Ошибки: 400 — пустой/некорректный запрос, 413 — размер, 415 — формат, 422 — невозможность извлечения, 408 — медленная загрузка, 503 — заняты обработчики.

## Обработка документов

- Максимум 10 МиБ на запрос, включая поток без Content-Length; 30 секунд на загрузку и обработку. Два одновременных запроса на процесс API.
- Каждый документ разбирается в отдельном процессе: до 15 секунд реального времени, 10 секунд CPU, 512 МиБ виртуальной памяти; процесс завершается и при отмене запроса.
- Имя файла никогда не используется как путь. Файлы передаются в памяти; ZIP не распаковывается на диск. Нет исходящих запросов к ссылкам документа и запуска встроенного кода.
- DOCX: проверяются сигнатура, обязательные части, пути, дубликаты ZIP, шифрование, макросы, XML DTD/entities; максимум 2000 частей, 40 МиБ суммарно после распаковки, 10 МиБ на часть, коэффициент сжатия до 200.
- PDF: проверяется сигнатура и структура, отклоняются документы с паролем и свыше 200 страниц. Пустые документы и сканы без текстового слоя возвращают понятную ошибку. Максимум 1 000 000 символов извлечённого текста.
- Текст выводится React как текст, не HTML. Ответы имеют `Cache-Control: no-store`. Содержимое документов не записывается в логи.

DOCX извлекается в порядке основных абзацев и таблиц. Колонтитулы, сноски, текстовые поля и вложенные таблицы полностью не поддерживаются. Для PDF сложные колонки, шрифты и порядок чтения могут снижать качество; для смешанных PDF выводятся только страницы с извлекаемым текстом. Точность и полноту пользователь проверяет по оригиналу.

Это локальная основа приложения. Перед публичным развёртыванием нужны аутентификация, TLS, лимиты запросов на reverse proxy, политика хранения и дополнительная изоляция процесса/контейнера. Лимит одновременности действует на каждый Uvicorn worker. Приложение не является антивирусом.

## Зависимости и решения

FastAPI обслуживает API; React/TypeScript с Vite — интерфейс. `python-docx` (MIT) читает DOCX; `pypdf` (BSD-3-Clause) извлекает PDF-текст без внешних исполняемых программ; `defusedxml` (PSF) отклоняет DTD/entities до обработки DOCX. Прямые зависимости интерфейса React/Vite/TypeScript используют MIT/Apache-2.0. Версии Python-зависимостей закреплены в `backend/requirements.txt`, JavaScript — в `frontend/package-lock.json`. Лицензии поставляются в установленных пакетах; это техническая проверка совместимости, не юридическое заключение.

Требования редакторской проверки находятся в `docs/editorial-criteria.md`. Эта версия их не исполняет и не оценивает происхождение текста или результаты антиплагиата.

## Реестр редакторских критериев (P0)

Добавлен [JSON-реестр 1.0.0](backend/app/data/editorial-criteria.v1.json) всех 34 критериев со строгими Pydantic-схемами и тестами соответствия Markdown. В исходнике исправлена нумерация внутри пункта 32. Реестр пока не анализирует документы.

```bash
(cd backend && ../.venv/bin/python -m app.editorial_registry)
```

[Формат, проверка и версионирование](docs/editorial-registry.md). [Неоднозначности](docs/editorial-ambiguities.md), включая отсутствующие в источнике description, зафиксированы явно; новые условия проверки не добавлены.

## Проекты (первая поставка P1)

[Настройка PostgreSQL, миграции, API, интерфейс и интеграционные тесты](docs/projects.md). Для полного backend-прогона задайте TEST_DATABASE_URL отдельной тестовой PostgreSQL-БД. Без неё тесты БД явно пропускаются; CI запускает их с реальным PostgreSQL.

## Рукопись (P2)

В выбранном проекте нажмите «Открыть рукопись». Создавайте план, абзацы, списки, таблицы и заготовки ссылок, сравнивайте и восстанавливайте версии. Выполните `alembic upgrade head` для миграции `0002_manuscripts`. [Руководство P2](docs/manuscripts.md) описывает конфликты двух вкладок, повтор сохранения, ограничения импорта и сохранность черновиков. Работа полностью ручная, без моделей и внешней передачи текста.

## Библиотека (первая поставка P3)

В проекте нажмите «Открыть библиотеку источников». Выполните `alembic upgrade head` для `0003_sources`. Ручные карточки работают без внешних ключей. Поиск передаёт только явно разрешённый запрос выбранным каталогам; дубликаты и расхождения показываются для ручного решения. [Настройка, API и ограничения](docs/sources.md). Оба API доступны через штатный прокси; архивный live-прогон обнаружил непопадание FAIR в top-5 Crossref; это диагностический результат ранжирования, а не отсутствие статьи. См. протокол в docs/sources.md.

Корпусная лингвистика, Editorial Review v2 и SQ01–SQ10 описаны как [будущие модули](docs/research-quality.md); они пока не выполняют проверки.

## Доказательства и план (P4a, серверный API)

Добавлены неизменяемые ручные фрагменты с локаторами, тезисы с поддерживающими/противоречащими свидетельствами и версии карты citations на конкретной рукописи. Выполните `alembic upgrade head` для `0004_evidence_plan`. [API, примеры и ограничения](docs/evidence.md). Интерфейс P4b доступен из сохранённой рукописи кнопкой «Открыть научные доказательства». Научная проверка тезисов и автоматический перевод пока не реализованы.

## Экспорт Word (P5)

В рукописи нажмите «Открыть экспорт Word». Выберите сохранённые версии рукописи и научного плана, стиль, профиль и титульные данные; выполните предварительную проверку и скачайте DOCX. Поддержаны структура P2, таблицы, колонтитулы/страницы, поле оглавления и ссылки на точные SourceVersion. [Руководство, воспроизводимость и ограничения](docs/exports.md). Начальный профиль — пользовательский пример, не официальный стандарт университета или проверенное оформление ГОСТ. Новых миграций и зависимостей нет.

### P6: critical foundation (mock only)

[P6 architecture](docs/p6-architecture.md) and
[Sol implementation handoff](docs/p6-implementation-handoff.md) specify bounded
model jobs, budgets, exact-context consent and safe section acceptance. The
internal `app.model_jobs.ModelJobs` service and `app.model_worker.run_once` use
PostgreSQL and a local mock; no AI API routes or real provider are enabled.
Apply additive migration `0005_model_jobs` via the existing Alembic setup.
`TEST_DATABASE_URL=… python -m pytest -q tests/test_model_jobs.py` runs the
foundation invariants from `backend/`. No model API key is required. Existing
manual editing, evidence and DOCX export remain independent of model execution.

P6 Task A adds the [owner-only API and supervised mock worker](docs/p6-task-a.md),
immutable decision audit (migration 0006), budget reconciliation/unfreeze and an
optional Compose `models` profile. Set `MODEL_OWNER_TOKEN` for the API; all model
providers remain mock-only until a real provider is approved. Manual workflows
remain available when model API is disabled. See the runbook for the personal
single-owner deployment boundary and explicit limits of these checks.

[P6 Task B](docs/p6-task-b.md) adds deterministic Evidence-grounded section
composition, complete contradiction/limit accounting, bibliography diagnostics,
versioned prompts and separate semantic-review jobs. The local reviewer reports
uncertainty; owner-authenticated human reviews need no model execution or budget.
Real LLM generation/review remains disabled pending provider approval.

[P6 Task C: AI Research Assistant](docs/p6-task-c.md) is available from the manual
manuscript editor. It previews saved research context, requires request-specific
consent, tracks/reopens jobs and safely accepts appended sections. The provider
remains a local mock/template composer. The owner token stays in memory; per-tab
request UUIDs/settings survive refresh without storing source excerpts or keys.

[P6 Task E](docs/p6-task-e.md) provides an **off-by-default** OpenAI Chat Completions
adapter with strict structured output, conservative reservations and separate
application credentials. Review the snapshot's deprecation, pricing/data policy
and explicit owner activation steps before enabling. Regular tests make no paid
requests; mock/manual mode stays available. P6 is not declared complete.
