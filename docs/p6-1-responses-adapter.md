# P6.1 — staged Sol Responses adapter

4 ноября 2026 года. Main `bc1d4f3` содержит PR #25, но PR #26 был объединён
в зависимую ветку `0c66969`. Интеграционный PR #27 переносит существующую историю
на main merge-коммитом `7c81489`, без копирования реализации. Этот adapter PR
зависит от #27; ни один PR агентом не объединяется.

## Реализованный контракт

`app/model_adapters/openai_responses.py`: фиксированные model `gpt-6.1-sol` и
`https://api.openai.com/v1/responses`, отдельный Responses codec. TaskSpec и
production gateway registry **не расширены**. `ready()` всегда отказывает;
`generate()` допускает только httpx.MockTransport. Реальный HTTPTransport,
ключ/approval в environment, переименование провайдера не включают выполнение.
Это разработанный и контрактно проверенный адаптер, не live-подключение.

Запрос содержит один scoped контекст, server instructions, original quotations,
строгий text.format/json_schema для Proposal либо SemanticReview. Для writing
обязательны section_id и совпадающая метка выбранного раздела в packet. Сервер
подготавливает packet; адаптер не читает другие проекты/рукопись и не вызывает
URL из источников. Не зарегистрированный адаптер нельзя передать public worker
через API. TaskSpec старых jobs остаётся совместимым.

Параметры: reasoning low/medium/high/xhigh/max, max_output_tokens 256–8000,
service_tier=default, store=false, background=false, stream=false,
truncation=disabled, implicit cache ttl=30m. Нет tools, continuation/history,
SDK retries или redirects. Режим/профиль региона/payload связаны с quote hash.
Оригиналы сохраняются, основной текст запрашивается на русском. Структурная
проверка идентификаторов/цитат/противоречий остаётся серверной; смысловая истина
этим не устанавливается. Генерация и рецензия — разные jobs и разные consent.

Граница 8000 сохранена от P6, а не объявлена достаточной для высоких effort:
reasoning может исчерпать её до появления текста. Incomplete/refusal/schema
failure с известным usage оплачивается и отклоняется без repair/retry.

## Официальные основания

Повторно изучены актуальные страницы (без платных вызовов):

- [Модель](https://developers.openai.com/api/docs/models/gpt-6.1-sol): ID,
  контекст 1050000, выход 128000, efforts и long-context threshold 272K.
- [Компактная Python reference](https://developers.openai.com/api/reference/python/resources/responses/methods/create):
  Responses request/result и usage. Markdown reference не открылся web tool из-за
  content-type; использована официальная HTML Python-страница.
- [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching):
  cache_write_tokens, разбиение ttl_30m_tokens/ttl_12h_tokens и отсутствие
  пересечения с cached_tokens. При пустых/отсутствующих деталях наш codec
  отказывает строже минимального API, а не оценивает недостающую стоимость.
- [Pricing](https://developers.openai.com/api/docs/pricing): обычный/кешированный
  вход и два lifetime записи; надбавки длинного контекста, региона и tier.
- [Reasoning](https://developers.openai.com/api/docs/guides/reasoning): reasoning
  включён в общий output cap; incomplete может быть платным без видимого текста.
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
  Responses text.format; локальный Proposal/SemanticReview контракт дополнительно
  ограничивает provider schema и отказывает на неверных научных ID/цитатах.
- [Data controls](https://developers.openai.com/api/docs/guides/your-data) и
  [lifecycle](https://developers.openai.com/api/docs/deprecations): store=false
  не равно ZDR; условия кеша/abuse retention и аккаунта нужно подтвердить владельцу.
  Shutdown для Sol при проверке не найден, это не гарантия будущей доступности.

Документация подтверждает API ID, но entitlement аккаунта не проверен. В среде
нет application key и разрешения api.openai.com. Реальных inference/counting
запросов 0. Прямой shell fetch документации или обход сетевой политики не применялся.

## Строгий billing

Все счётчики целые, неотрицательные; bool/float/null, неизвестные поля (даже
нулевые), отсутствие details, неверные суммы или превышение bounds отклоняются.
Обязательны input/output/total; input details cached/write/два lifetime;
output details reasoning. cached + write <= input, два lifetime суммируются в
write, reasoning <= output, total = input + output <= context. Reasoning —
подмножество output, второй раз не оплачивается.

Для Standard global используются ставки USD / миллион: ordinary=2,
cached=0.10, write30m=2.50, write12h=5, output=10. При input > 272000 входные
ставки умножаются на 2, выходная на 1.5 для всего запроса. Явный server-owned
regional profile добавляет 10%; неизвестный tier/model ведёт к UnconfirmedBilling.
Регион по response не угадывается; его должен подтвердить владелец аккаунта.
Бинарные float для денег не используются, итог округляется вверх в micro-USD.

Резерв: полный context minus output cap по наибольшей цене записи (12h) и
long-context ставкам плюс полный output cap. Для cap=2000: global 10510000
micro-USD ($10.51); regional 11561000 ($11.561). Это преднамеренно большой
верхний резерв, а не оценка малого запроса. Официальный counting endpoint
не вызывается без согласия. Проверка токенизатора не заменяется символами.

Неизвестный usage/model/tier → существующий budget freeze и удержание резерва.
HTTP error/timeout/потеря ответа → ambiguous без повтора и без предполагаемого
возврата. Отмена во время отправки означает discard результата, но известный
расход сохраняется. Сбой БД после ответа удерживает резерв. Оплаченный invalid
output сохраняет рассчитанную стоимость. GatewayReply получает аддитивные
billing_details; они сохраняются в report и при invalid/cancelled, без raw
provider response, reasoning traces или ключей. Старые четырёхаргументные reply
и immutable settlements/acceptance не меняются. Миграции не требуются.

Нет обещания provider-enforced spending cap или точно совпадающего налогового
инвойса. Необъявленная смена тарифа не обнаруживается только по счётчикам.

## Тесты и ограничения

`tests/test_sol_responses.py`: HTTP request/schema и пять efforts; 401/403/429/5xx/
redirect без retries; invalid JSON/duplicate keys, refusal/incomplete/tool output;
missing/unknown usage, boolean/negative counts, границы, кеш lifetime sums,
reasoning без двойной оплаты; regional, threshold 272000/272001, property sweep
для cost <= reserve. Известные численные примеры проверяют ordinary/cached/30m/12h.

Worker-тесты используют **только тестовый Bridge от MockGateway**, чтобы проверить
существующие PostgreSQL транзакции с Responses reply: charge, freeze следующей
задачи, нехватку бюджета, отмену во время вызова, lost DB/timeout, invalid source/
quote, version conflict, acceptance replay и отдельный review consent/cost.
Сохранённый envelope этого Bridge имеет старый допускаемый TaskSpec; это не
утверждение, что production Sol job уже можно enqueue. Public rejection тест
сохранён. Тестовый транспорт не использует credentials приложения.

Полный suite сохраняет научные сценарии экономики/менеджмента/финтеха, project
isolation, rich objects, UUID, Citation, детерминированный DOCX и миграции.
Человеческое научное качество и реальный Sol API остаются blocked/unmeasured.

## Перед первым настоящим вызовом

1. Владелец рассматривает #27 и отдельный adapter PR; никаких автоматических merge.
2. Проверяет entitlement, актуальные pricing/lifecycle и условия региона/retention.
   При необходимости штатно разрешает api.openai.com, предоставляет отдельный
   application key; ключ Codex/ChatGPT не подходит.
3. Нужен отдельный review активации: allowlist/TaskSpec, закреплённая конфигурация
   mode/output/region, API/worker routing, credential gate, UI/consent и ограничения
   section context. Нельзя просто убрать ready() и добавить ID одним изменением.
4. Повторяет контрактные тесты на актуальной reference; подтверждает достаточность
   резерва и осознанно принимает строгий отказ при изменении usage. Режимы fast/
   ultrafast/flex/batch, инструменты и изображения не входят в этот контракт.
5. Разрешает ровно один synthetic writing request по сохранённому UUID/context hash
   и утверждённому бюджету. Review требует отдельного разрешения и резерва.
   Timeout/invalid не разрешают второй вызов. Сохраняются usage/cost/report и
   экспертная оценка текста, без секретов.

До этой отдельной активации никакое действие владельца только в environment
не может вызвать Sol из данного приложения. Mock/manual/DOCX доступны.

## Наблюдаемые проверки

- Интеграция #27: 332 backend passed, zero skips, 63.67 s; CI push/PR success.
- Новый adapter: полный локальный набор 388 passed, zero skips, 95.52 s;
  затем добавлены три сценария с Responses fixtures и запущен целевой набор.
- Frontend: 53 passed; TypeScript/Vite build passed.
- Chromium 154 с настоящими локальными API/PostgreSQL/worker: один enqueue,
  reload/UUID, mock review через API, accept, DOCX download, restore без rebasing;
  0 page errors и 0 внешних запросов. [JSON результата](validation/p6-1-responses/browser.json).
- Полный backend включает migration upgrade/downgrade/re-upgrade/check,
  совместимость P2–P5.1 и защиту PR #22–23. Новых миграций/dependencies нет.

Сохраняется известное deprecation warning Starlette TestClient/httpx. Реальных
API calls 0; модельная научная адекватность/качество письма не измерены.
