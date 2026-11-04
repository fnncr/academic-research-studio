# Независимый аудит P6

Дата: 4 ноября 2026 года. Исходная `main`: `99ef8b9b769e7dfc0aa46862b082eca747f1705a`
(PR #22). Проверены исходники и поведение, а не только предыдущие отчёты.
Финансовое исправление: [PR #23](https://github.com/fnncr/academic-research-studio/pull/23),
коммит `09d685e`. Аудит не является независимой организационной сертификацией.
Этот отчёт поставляется отдельным PR от main и не включает код исправления:
перед включением внешнего провайдера #23 должен быть рассмотрен и объединён.

## Заключение и границы готовности

**P6 не готов к регулярной работе с настоящей LLM.** После принятия исправления
#23 программная основа пригодна для контролируемой локальной работы одного
исследователя: ручной редактор, сохранённые доказательства, mock-предложения,
явное принятие и DOCX. Отдельная live-приёмка, качество реальной генерации,
проверка счетов и эксплуатационное восстановление пока не подтверждены.

Внешний адаптер остаётся отключённым. Live-статус: **blocked** — нет отдельного
разрешения, настроенного ключа приложения и разрешённого сетевого доступа к
api.openai.com. Запросы к реальной модели: **0**. Никакие пользовательские
исследовательские тексты провайдеру не передавались.

Формальные локальные проверки P7 можно проектировать независимо от live P6;
условия и границы приведены в [p7-readiness.md](../p7-readiness.md). Реализация
P7/P8/P9 в этот аудит не входит.

## Основания и воспроизводимость

Изучены AGENTS.md, architecture/roadmap, ADR 0006, P6 architecture/handoff/tasks
A/B/C/E, final-integration и recovery-runbook. Проверены HTTP-контракты, SQL
транзакции и триггеры, gateway/worker, P2/P4 acceptance, P5/P5.1 export и React.
Исторические документы не переписаны как описание сегодняшнего состояния.

GitHub подтвердил объединение #15–22. Важно: #16 → feat/p6-architecture,
#17 → feat/p6-critical-foundation, #18 → feat/p6-gateway-api; #19 доставил эту
цепочку в main. #20–22 объединены в main. Проверенный CI исходной main:
[41746324010](https://github.com/fnncr/academic-research-studio/actions/runs/41746324010), success.

| Проверка | Фактический результат |
| --- | --- |
| Исходная main: полный backend/PostgreSQL | 314 passed, 0 skips, 53.38 s |
| Исходная main: frontend | 52 passed, 8 файлов, 17.83 s |
| Новые финансовые контрпримеры до исправления | 5 failed / 5 passed: дефект воспроизведён |
| Целевые проверки исправления | 35 passed, 12.48 s |
| Полный backend после исправления | 325 passed, 0 skips, 53.35 s |
| TypeScript + Vite | passed |
| Миграции | upgrade/downgrade/re-upgrade/check в одноразовых схемах прошли в полном наборе |
| Настоящий Chromium | 154.0.8037.57, локальный UI → API → PostgreSQL → worker → DOCX passed |
| Office | LibreOfficeDev 26.8: открытие, PDF 3 страницы A4, визуально просмотрены все страницы |
| Microsoft Word / screen reader / платная модель | не выполнено |

CI исправления #23 на `09d685e`: [push 41800330120](https://github.com/fnncr/academic-research-studio/actions/runs/41800330120)
и [pull_request 41800395576](https://github.com/fnncr/academic-research-studio/actions/runs/41800395576)
— success. Число 325 относится к исправленному коду #23; отдельный PR отчёта
от исходной main имеет прежний набор из 314 backend-тестов до объединения #23.

После перезапуска среды тестовая БД отсутствовала: один промежуточный прогон
получил connection refused. Восстановлен одноразовый PostgreSQL 17, затем выполнен
полный успешный прогон. Ошибка среды не засчитана как успех. Осталось известное
предупреждение Starlette TestClient/httpx о deprecated-интеграции.

Команды из backend (DATABASE_URL тестов должна вести только на тестовую БД):

```sh
TEST_DATABASE_URL=postgresql+psycopg://studio@127.0.0.1:55432/studio_test \
  ../.venv/bin/python -m pytest -q
TEST_DATABASE_URL=postgresql+psycopg://studio@127.0.0.1:55432/studio_test \
  P6_BROWSER_ARTIFACT_DIR=/tmp/p6-browser-audit \
  ../.venv/bin/python tests/browser/run_smoke.py
```

Из корня: `npm --prefix frontend test`, `npm --prefix frontend run build`.
Browser runner требует установленный Playwright для Node и Chromium (в этой
среде уже были); это необязательное средство аудита, не новая зависимость
приложения/обычного CI. Он создаёт и удаляет отдельную схему, запускает настоящие
процессы API/worker/Vite, снимает approval/key OpenAI, использует публичный
одноразовый тестовый owner token. Порты 8000/5173 должны быть свободны.
Обычный pytest блокирует реальный HTTPTransport к OpenAI через conftest.py.

## Архитектурные выводы

| Инвариант | Проверка и вывод |
| --- | --- |
| Разделение обязанностей | model_context/grounded_writing/semantic_review отвечают за данные и валидацию; gateway за транспорт; model_jobs за транзакции; model_worker за жизненный цикл. Parser worker.py не объединён с LLM worker |
| Минимальность | Нет нового брокера, Redis, SDK модели, векторной БД. Исправление не добавляет зависимости/миграции |
| Транзакции | Project → Job → Budget; claim берёт только Job SKIP LOCKED и сразу commit. Вызов gateway находится после dispatch commit, вне транзакции |
| Несколько workers | PostgreSQL race-тесты проверяют единственный claim, фехтование просроченного lease, конкурентный reserve/finish/accept. Heartbeat не оживляет истёкший token |
| Сбой после отправки | Durable dispatch UUID, ambiguous, резерв удержан. Ни recover, ни UI polling не создают второй вызов. Это не exactly-once billing провайдера |
| Принятие | Одна транзакция создаёт ManuscriptRevision, ResearchPlanRevision, references и ModelAcceptance. Повтор receipt обрабатывается до сравнения актуальных heads. Ошибка INSERT откатывает все записи |
| Версии/цитаты | Старые блоки deep-copy без переписывания, новые UUID5 от job, прежние диапазоны проверяются снова; stale manuscript или plan дают конфликт без rebase |
| Воспроизводимость | Сохраняются input/result и хеши, model/prompt/schema/pricing; повтор чтения не генерация. DOCX идентичен при одинаковых сохранённых входах. Новая LLM-генерация не обязана быть идентичной |
| Изоляция | API и сервисы используют project predicates; чужие Evidence/SourceVersion/jobs отклоняются. Это один владелец всех проектов, а не межпользовательская авторизация |
| Доступ | MODEL_OWNER_TOKEN защищает P6, но P2–P5 остаются персональными маршрутами. Весь сервис должен быть loopback либо за аутентифицированным TLS proxy; публикация старых API в Интернет небезопасна |
| Недоверенный текст | Отдельные system/data messages, нет tools/shell/произвольного fetch; React выводит строки. Это ограничивает последствия injection, но не доказывает смысловую устойчивость модели |

Основания: [model_jobs.py](../../backend/app/model_jobs.py),
[worker](../../backend/app/model_worker.py), [контекст](../../backend/app/model_context.py),
[API](../../backend/app/model_api.py), [миграция 0005](../../backend/migrations/versions/0005_model_jobs.py),
[race/fault tests](../../backend/tests/test_model_jobs.py),
[API/worker tests](../../backend/tests/test_model_api.py).
Решения соответствуют ADR 0006. Его статус «proposed for owner review» не
заменён самовольно на approved; факт merge не используется как выдуманный ADR sign-off.

## Находки и классификация

| ID / уровень | Находка | Состояние / действие |
| --- | --- | --- |
| A01 Critical | Неполный usage мог быть принят как окончательная стоимость; повреждение usage не всегда блокировало следующие расходы | Исправлено в #23, 5 регрессий; [подробности](https://github.com/fnncr/academic-research-studio/blob/fix/p6-usage-contract/docs/validation/p6-billing-audit-fix.md) |
| A02 Medium | `_settle` отвергал документированную границу входа >1 млн вопреки своей котировке | Исправлено в #23; граница берётся из сохранённой quote |
| A03 Medium | UI умеет читать review jobs, но не создавать отдельную SemanticReview/human review; Task тип не содержит review-полей | Подтверждено кодом и browser flow. Нужен отдельный UI PR с собственным consent/budget; сейчас запуск через API |
| A04 Medium | Принятые модельные абзацы имеют P2 origin=manual; receipt сохраняет происхождение, но обычный редактор не показывает модельный provenance по абзацам | История не потеряна. Нужна проекция receipt в UI, без изменения старых JSON/enum; не считать manual доказательством авторства |
| A05 Medium | SemanticReview получает полный Proposal, включая объяснения генератора; coverage определяется цитируемыми абзацами, а не всеми свободными утверждениями | Независимость задачи/бюджета есть, слепой рецензии и полноты смыслового покрытия нет. Для P8 нужна отдельная политика/версия контракта, решение владельца |
| A06 Medium | Тариф фиксирован конфигурацией, drift блокирует только проект; общей остановки всех проектов автоматически нет | При инциденте отключать approval/worker глобально по runbook. Уже отправленные вызовы не отзываются. Потребность в глобальном circuit breaker — отдельное решение |
| A07 Low | История UI ограничена последними 20 заданиями; выбранная версия brief автоматически последняя при connect | Старые ID читаются напрямую, но навигация/выбор brief ограничены; будущий небольшой UI PR |
| A08 Low | Roadmap использует P7a/P7b в двух разных смыслах; часть документов описывает исторический mock-only статус | В p7-readiness явно разведены два плана; исходные критерии/архитектура не переписаны |

Новых подтверждённых High в части потери рукописи/цитат/изоляции не обнаружено.
Это ограниченный аудит, а не доказательство отсутствия иных дефектов. Возможные
ошибки содержательной политики A05 не исправляются скрытым ужесточением acceptance:
это изменило бы требования к автору и исторические review-контракты.

## Финансовая безопасность и практичность

Резервирование, конкурентное списание, отмена до/после dispatch, таймаут,
потеря ответа/БД, смерть worker и поздний ответ проверены тестами. Списание
ровно один раз обеспечивается транзакцией/уникальным settlement. Invalid paid
output оплачивается; unknown не равен нулю. Cancel после отправки — намерение,
не обещание возврата. Reconcile и unblock — разные аудируемые решения владельца.

Для output=2000 резерв составляет **421431 micro-USD ($0.421431)**. Формула:
ceil(((1047576−output)×0.4 + output×1.6)) в micro-USD. Реальный маленький запрос
может стоить намного меньше, но это не оценка его точного числа токенов.
Проверены 606 комбинаций границ и округления, включая кеш.

Предложение отдельно от исправления: добавить отображаемую приблизительную
оценку для удобства, сохранив текущий резерв. Уменьшать резерв допустимо только
после версионированного tokenizer + доказанного upper bound на framing/schema,
контрактных тестов RU/EN/Unicode и проверки фактических usage. Не вводить
коэффициент «примерно четыре символа на токен» как финансовую гарантию.
Внешняя цена, налоги/регион и счёт провайдера локальной арифметикой не доказаны.

## Научные контрпримеры

Все тексты синтетические; «существующий источник» здесь означает сохранённую
запись с допустимым ID, а не новую внешнюю проверку публикации.

| Сценарий | Что проверяется программно | Что остаётся исследователю |
| --- | --- | --- |
| 1. Вымышленный DOI | Плохой синтаксис отклоняется P3; неизвестный source UUID отклоняется P6 | Синтаксически правильный ручной DOI и DOI внутри prose могут пройти. Нужны реестр/полный текст; offline не доказывает существование |
| 2. Источнику приписан чужой вывод | Версия/UUID/точная цитата проверяются | Entailment не установлен; новый characterization-тест принимает ошибочный prose только с semantic=uncertain |
| 3. Противоречивые результаты | Полный evidence closure, dispositions и review targets не допускают потери relation | Объяснения могут быть поверхностными; сохранение relation не гарантирует честного изложения в тексте |
| 4. Причинность из корреляции | Структура остаётся допустимой | Новый тест демонстрирует этот предел; нужен дизайн исследования и экспертная SQ03/SQ04/SQ10 проверка |
| 5. Поддельная цитата | Несовпадение UTF-16/сохранённой selection отвергается | Пользователь мог изначально записать выдуманный excerpt; full_text/locator остаются unverified |
| 6. Неверный перевод | Оригинал/язык сохраняются отдельно, автоматического перевода нет | Неверный paraphrase/перевод в prose проходит структуру, требует двуязычной проверки |
| 7. Неполная библиография | authors/year отмечены missing_fields, экспорт имеет preflight | Не дополнять догадкой; пользователь находит выходные данные |
| 8. Старая SourceVersion | Новая версия не подменяет цитируемую; end-to-end изменяет метаданные во время генерации | Устаревание/ретракция не проверяются автоматически; старая версия может быть сознательно выбрана |
| 9. Чужой проект | Реальные чужие Evidence/SourceVersion/job IDs отклоняются | Нет обещания многопользовательской изоляции за пределами single-owner модели |
| 10. Prompt injection | Строка остаётся JSON-данными; дополнительные tools/actions/verified отклоняются; React не выполняет HTML | Модель может следовать вредоносному смыслу в обычном prose; устойчивость реальной модели не измерена |

Исполняемые основания: [test_p6_audit.py из #23](https://github.com/fnncr/academic-research-studio/blob/fix/p6-usage-contract/backend/tests/test_p6_audit.py),
[test_grounded_writing.py](../../backend/tests/test_grounded_writing.py),
[test_model_jobs.py](../../backend/tests/test_model_jobs.py),
[test_sources.py](../../backend/tests/test_sources.py),
[test_evidence.py](../../backend/tests/test_evidence.py),
[test_p6_end_to_end.py](../../backend/tests/test_p6_end_to_end.py),
[ModelAssistant.test.tsx](../../frontend/src/ModelAssistant.test.tsx).
Ни один зелёный тест не означает «научно подтверждено».

## OpenAI: повторная сверка официальной документации

Проверено 4 ноября 2026 года через web tool, без inference-запросов:

- [Модель](https://developers.openai.com/api/docs/models/gpt-4.1-mini): snapshot
  gpt-4.1-mini-2025-04-14 помечен deprecated; context 1047576, output 32768;
  input/cached/output $0.40/$0.10/$1.60 за миллион токенов.
- [Lifecycle](https://developers.openai.com/api/docs/deprecations): shutdown
  14 января 2027 года; локальный ready() отказывает с этой даты. Наличие в
  документации не подтверждает доступ конкретного аккаунта.
- [Chat API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
  и [structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
  strict schema с required/additionalProperties; refusal/truncation всё равно
  возможны. Локальная проверка строже provider schema; исправления JSON нет.
- [Authentication](https://developers.openai.com/api/reference/overview): серверный
  bearer key; адаптер читает только отдельный ARS_OPENAI_API_KEY. X-Client-Request-Id
  используется диагностически, гарантии billing deduplication нет.
- [Limits](https://developers.openai.com/api/docs/guides/rate-limits): зависят от
  аккаунта/модели. 401/403/429/5xx/redirect и потеря ответа не повторяются.
- [Data controls](https://developers.openai.com/api/docs/guides/your-data): API не
  используется для обучения по умолчанию; abuse retention до 30 дней, возможны
  условия кеша/контракта. store=false не означает ZDR. Регион/договор подтверждает владелец.

В коде: фиксированный endpoint/TLS, без SDK retries/tools/audio/reasoning,
max_completion_tokens, n=1, service_tier=default, store=false. Read timeout 45 s,
connect 10 s, elapsed 60 s проверяется между chunk: это не жёсткий wall-clock
deadline, последний read может его продлить. Принудительное завершение после
dispatch оставляет ambiguous. Изменённые model/tier/billing поля блокируют бюджет.
Ключ, price confirmation, approval и per-call cap нужны одновременно; mock
и ручной режим доступны без них. Тариф не сверяется онлайн автоматически.

## Browser и DOCX

[Исполняемый runner](../../backend/tests/browser/run_smoke.py) и
[Chromium сценарий](../../backend/tests/browser/smoke.cjs) используют настоящие
процессы. Проект/задание/источники/Evidence/Claim/богатая рукопись подготовлены
через реальные API существующих fixture helpers. Через UI выполнены выбор
версии/тезиса, preview, отдельное согласие с клавиатуры, enqueue, polling,
reload, ввод owner token заново, восстановление UUID, принятие и DOCX download.
Review создан отдельным API consent, поскольку кнопки UI нет. Затем через UI
восстановлена старая версия новым сохранением: предупреждение о черновике
показано, принятый архив не изменился, citations остались у прежней версии.
Ручная полная
проходка создания всех объектов мышью и screen-reader аудит не заявляются.

Результат: ровно один writing enqueue браузером после reload, original blocks
сохранены, review=uncertain, 0 page errors, 0 внешних браузерных запросов.
Проверены viewport 1440×1000 и 390×844; у assistant нет горизонтального overflow.
Скриншоты просмотрены. Это автоматизированный real-browser smoke с визуальным
просмотром артефактов, а не полная ручная UX/assistive-technology приёмка.

Артефакты синтетического запуска:
[JSON](artifacts/p6-audit/result.json),
[desktop](artifacts/p6-audit/assistant-desktop.png),
[mobile](artifacts/p6-audit/assistant-mobile.png),
[скачанный DOCX](artifacts/p6-audit/browser-accepted.docx),
[PDF из LibreOffice](artifacts/p6-audit/browser-accepted.pdf).

DOCX SHA-256 `509c678ec694cc7893da89aa838907ad88485d02ee930ccb72782a3c1f7dc000`.
PDF SHA-256 `2b9dc1cf539f2e84c9fe4c0bb8ba354afb63e86651e8d2eeff04fb9b0fae4d2d`.
Все три страницы просмотрены: кириллица/EN, PNG, формула, обычная и объединённая
таблицы, сноска, ссылки/библиография, номера страниц; обрезания/наложения не
наблюдалось. Times New Roman заменён Liberation Serif. TOC требует обновления
полей для номеров страниц. Word и официальный шаблон Финансового университета
не проверены, соответствие им не заявляется.

## Условия следующей приёмки

1. Владелец рассматривает и объединяет #23; общий аудит не объединяет его сам.
2. Принять решения по UI review/provenance и будущей слепой рецензии.
3. Отработать backup/restore в целевой установке, защитить все маршруты доступа.
4. Выполнить [ограниченный live-протокол и экспертную оценку](p6-live-acceptance.md)
   после отдельного разрешения. Не заменять synthetic success оценкой реальной науки.
5. Проверить DOCX в Microsoft Word с нужными шрифтами и предоставленным шаблоном.

До этого допустима локальная работа под ответственностью исследователя;
автономное производство научно достоверных текстов и завершённость P6 не заявляются.
