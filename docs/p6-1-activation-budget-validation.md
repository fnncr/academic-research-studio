# P6.1 — activation и budget validation

Основание main `10fa346`: PR #22–28 фактически включены, включая зависимые
#26/#28 до интеграционного merge #27. Работа ведётся в отдельной ветке
feat/p6-1-sol-activation-budget. Платных inference/counting вызовов: **0**.
Пользовательские исследования внешним провайдерам не передавались.

## Активация и реальные контракты

Интегрирован model `gpt-6.1-sol`, fixed endpoint
`https://api.openai.com/v1/responses` в TaskSpec, API preview/consent/enqueue,
PostgreSQL worker, обработку результата и UI. Прежние MockGateway и старый
OpenAI adapter сохранены. Public provider=openai, model выбирает конкретный
адаптер. Исторические задания читаются; старые queued задачи с несовпавшим
payload quote могут fail closed до отправки, без автоматической регенерации.

Перед реализацией повторно проверены официальные источники:
- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/api/docs/guides/prompt-caching
- https://developers.openai.com/api/docs/guides/token-counting
- https://developers.openai.com/api/reference/python/resources/responses/methods/create

На 4 ноября 2026 года: Standard input/output $2/$10 за миллион; cached input
$0.10; write 30m/12h $2.50/$5. При input >272000 входные ставки ×2, output ×1.5;
regional profile +10%. Strict usage и long-context границы из PR #28 сохранены.
Reasoning входит в output cap, не прибавляется к нему вторым платежом.
Fast/ultrafast/flex/batch/tools не разрешены. Модель не имеет закреплённого
датированного snapshot в используемом ID; владелец повторно проверяет lifecycle.

Реализованные efforts: low/medium/high/xhigh/max; UI предлагает Standard Draft
(medium), Deep Academic Writing (high), Complex Research Review (xhigh), а также
low/max. Это параметры рассуждений, а не гарантии качества. Общий output cap
сохранён 256–8000 и может исчерпаться reasoning до появления текста.

### Все runtime gates обязательны

В environment API **и** worker:

```text
ARS_SOL_API_KEY=<отдельный серверный ключ приложения>
ARS_SOL_APPROVAL=sol-activation-2026-11-04-v1
ARS_SOL_DATA_POLICY=sol-activation-2026-11-04-v1
ARS_SOL_PRICE_CONFIRMED=sol-activation-2026-11-04-v1
ARS_SOL_MODEL=gpt-6.1-sol
ARS_SOL_REGION=global
ARS_SOL_MAX_UNITS=<подтверждённый per-call предел в micro-USD>
```

Регион допускает global/regional. Не угадывается по response. Ключ Codex/ChatGPT
не читается. Ключ никогда не передаётся frontend. Без любого gate enqueue
отказывает до reserve/send; отзыв конфигурации до dispatch завершает queued job
без списания. Бюджет проекта отдельно подтверждается owner API. Нужен owner
MODEL_OWNER_TOKEN и точное consent по fingerprint; конфигурация не заменяет
согласия на конкретный контекст. Default installation остаётся выключенной.

Для Sol обязательно выбран section_id. Контекст содержит выбранный раздел,
только selected claims и их полный supports/contradicts/limits Evidence closure,
исходные языки/цитаты и SourceVersion. PNG pixels не отправляются. Изменение
effort/региона/payload/quote требует нового согласия или блокирует dispatch.
UI сохраняет request UUID; review — отдельный task, consent и reserve. При
lost response не создаётся новый UUID. Структурная валидация остаётся unverified.

## Budget Estimator v1 и честный fallback

`app/budget_estimator.py` — отдельная версионированная компонента. Формирует
estimated_input_tokens, bounded_input_tokens, max_output_tokens,
reasoning_token_limit, estimated_cost/reserved_cost, pricing profile/version,
estimate_method, bound status, context/payload hash и payload bytes.

**Оптимизация гарантированного резерва остаётся blocked.** Нет проверенной
локальной границы для полного Responses payload (instructions/schema/framing).
Официальный input_tokens endpoint передаёт контекст наружу; его стоимость,
ограничения и отдельное согласие нельзя предполагать. Он не вызывается ни в
preview, ни worker. Tokenizer dependency не добавлена; «символы / 4» не применяется.
Условие задания позволяет полноценную активацию с консервативным fallback.

estimated_input_tokens/estimated_cost = null: прогноз не выдумывается.
reasoning_token_limit = null: отдельный независимый лимит API не изобретён;
общий max_output_tokens покрывает reasoning. bounded_input_tokens — контекст
минус output cap. reserved_cost — полное окно по максимальной 12h-write цене с
long-context надбавкой. Все деньги — целочисленные micro-USD с округлением вверх.

Для cap=2000 global bound 1048000, резерв 10510000 micro-USD ($10.51);
regional 11561000 ($11.561). Actual reported usage считается отдельно, unknown
расход остаётся ambiguous/held. Cache hit ratio не используется как граница.
Новый estimator не снижает reserve задним числом. Реальная оптимизация второй
части **не объявляется завершённой**; достигнуты интеграция/fallback/диагностика.

### Матрица синтетического документа

`python -m app.sol_budget_scenarios` создаёт 30 **логических** русских страниц
и RU/EN материал. Это локальный payload benchmark, не Word pagination и не
пять новых production видов анализа. Полный документ/выбранный раздел/генерация/
рецензия/спорный тезис различаются объёмом. Рабочие виды job — writing и review;
анализ полных документов/отдельных утверждений пока моделируется размером payload.
[JSON расчётов](validation/activation-budget/scenarios.json) содержит фактические
payload bytes, output cap=2000, метод, хеши, estimated=null, reserve=10510000 и
разницу со старым reserve=0 для каждого размера. Все строки используют fallback
с явной причиной. Цифры не являются реальным model usage.

## Защита и проверка

Payload связан с quote и estimator hash. Worker повторяет quote до dispatch;
изменение инструкций после consent даёт predispatch failure. Транзакции,
lease fencing, резервирование/settlement, acceptance receipt и правила отмены
из PR #22–23 сохранены. После dispatch неизвестность никогда не разрешает
повторную отправку; неподтверждённый usage/model/tier замораживает бюджет.
Известный расход сохраняется при refusal/incomplete/cancelled/invalid.

Полный PostgreSQL backend, frontend/build, миграции и Chromium проверяются
в PR. Добавлены реальные registry→queue→worker tests с заменой только HTTP
transport, все отдельные gates, отзыв конфигурации, изменение payload после
consent и fallback/hash tests. Существующие invalid JSON, 429/5xx, cache/reasoning,
конкурентность, источники, immutable версии, DOCX и rollback не ослаблены.
Три синтетических научных сценария сохранены; научное качество Sol не измерено.

## Первый настоящий вызов — отдельно от этой задачи

`python -m app.sol_live_acceptance --manifest /tmp/sol.json` без action печатает
blocked и не пишет БД/не вызывает provider. **В этом задании live сценарий не
запускался.** После отдельного разрешения владелец использует disposable
мигрированную DATABASE_URL и --prepare, просматривает весь manifest context,
endpoint/model/quote и подтверждает проектный бюджет/per-call cap и gates.
`--execute --owner-approval 'SEND ONE SYNTHETIC WRITING REQUEST'` разрешает
enqueue только подготовленного синтетического economics case, без вызова worker
в CLI. Один обычный gated worker выполняет его. Request UUID сохранён; повторный
запуск CLI возвращает тот же job, без второго reserve/send. --collect читает
usage/result/cost в manifest без сетевого модельного вызова. Quality rubric
заполняется исследователем. SemanticReview требует нового отдельного согласия.
Не запускать worker над очередью иных платных задач во время ограниченного live
эксперимента; использовать выделенную тестовую установку.

Текущий реальный доступ blocked: нет application key/owner approval и штатного
разрешения api.openai.com. Store=false не означает ZDR; cache/abuse retention,
регион, tariff/account entitlement и отдельное разрешение требуют владельца.
Сначала review/merge этого PR владельцем, затем контролируемая настройка и
точный synthetic запрос. P7/P8/P9 не реализовывались.

## Наблюдаемые проверки

Полный PostgreSQL suite: **404 passed**, zero skips, 94.31 s (затем добавлен
тест безопасного default CLI). Frontend: **54 passed**, build passed (затем
добавлен отдельный UI review-consent regression). CI исполняет окончательный набор.
Миграционные проверки включены в suite, миграций/dependencies не добавлено.
Chromium 154: один enqueue, UUID reload, отдельная рецензия через API, accept,
скачивание DOCX, restore без изменения архива/диапазонов; 0 page errors,
0 external browser requests. [JSON](validation/activation-budget/browser.json).
Автоматический browser smoke по-прежнему создаёт review через API; новая кнопка
UI рецензии отдельно проверена DOM-тестом. Это не реальная модельная проверка.

Добавленные финальные регрессии прошли: 14 targeted backend tests, **55 frontend
tests** и TypeScript/Vite build. Окончательный CI включает также безопасный CLI
default и отдельный UI review-consent; live-сценарий вне тестовых defaults не запускался.
