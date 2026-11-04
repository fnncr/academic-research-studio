# Продолжение P6.1

Основание main 513dd2e. PR #25 — read-only compatibility, не Sol adapter.
PR #26 (https://github.com/fnncr/academic-research-studio/pull/26), зависимая ветка feat/p6-1-evaluation-ui содержит три сценария,
подготовщик, UI блокировки и раздельного учёта расходов, тесты и документацию.
Ничего не объединено агентом; платных/counting API вызовов 0.

Сначала прочитать p6-1-model-compatibility.md и p6-1-validation.md.
Основные файлы: app/model_catalog.py, app/scientific_evaluation.py,
tests/test_model_compatibility.py, tests/test_scientific_evaluation.py,
frontend/src/ModelAssistant.tsx. PR #22–23 финансовая защита не изменена.

Открытые обязательные шаги перед реальным подключением:
1. Подтвердить доступ отдельного приложения к gpt-6.1-sol; получить разрешение
   владельца на provider/data/budget. Штатно разрешить API host, не обходить proxy.
2. Прочитать компактную официальную Responses usage/schema/cache-control reference.
   Подтвердить счётчики записи кеша по lifetime, long-context/tier/region тарифы,
   reasoning/output ceilings, timeout/refusal и structured output ограничения.
3. Отдельный adapter с fixed endpoint, без tools/retries, strict local validation,
   immutable payload hash и финансовой верхней границей. Не дописывать Sol ID
   в TaskSpec до этого контракта. Старые jobs должны оставаться читаемыми.
4. Добавить полный adapter MockTransport fault suite, разрешённые режимы/caps,
   consent-reset и separate SemanticReview. Проверить section-only context.
5. Только затем отдельный один live writing request; review — новое разрешение.
   Научная/стилистическая оценка текущего mock не заменяет качество Sol.

Команды и действительные результаты находятся в p6-1-validation.md. CLI
`python -m app.scientific_evaluation --output /tmp/live.json` безопасен по
умолчанию: blocked без БД/сети. --prepare пишет только синтетические объекты
в одноразовую мигрированную DATABASE_URL и никогда не вызывает модель.
P7/P8/P9 не начаты. Не утверждать, что вся P6.1 real integration завершена.

Финальный локальный прогон: 332 backend без skips, 53 frontend, build passed.

## Продолжение: Responses adapter под контрактными тестами

Интеграционная ветка integration/p6-1-pr26 / PR #27 переносит PR #26 на main.
Зависимая feat/p6-1-responses-adapter содержит app/model_adapters/openai_responses.py
и tests/test_sol_responses.py. Компактная официальная Python reference и кешовые
usage-счётчики прочитаны; строгие тарифы/границы реализованы.
Production ready() по-прежнему закрыт, allowlist не расширен. Реальных вызовов 0.
Перед активацией следовать docs/p6-1-responses-adapter.md, особенно owner/account/
network/region/data/budget и отдельному review маршрутизации API/worker.
Не считать старую fallback-формулировку «adapter отсутствует» актуальным статусом
реализации: adapter теперь существует, но не допущен к исполнению.
