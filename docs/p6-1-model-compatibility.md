# P6.1a — совместимость и блокировка Sol

Main `513dd2e`; PR #23–24 объединены. Проверено 4 ноября 2026 года.
Официальный ID gpt-6.1-sol подтверждён документацией; доступ аккаунта в текущей
среде не подтверждён: application key отсутствует, api.openai.com не разрешён.
Использован fallback задания: интерфейс совместимости без исполняемого адаптера.
Подключение Sol и качество реальной генерации не объявляются. Вызовов API: 0.

Официальные источники, прочитанные web tool:
- https://developers.openai.com/api/docs/models/gpt-6.1-sol
- https://developers.openai.com/api/docs/pricing
- https://developers.openai.com/api/docs/guides/prompt-caching
- https://developers.openai.com/api/docs/guides/token-counting
- https://developers.openai.com/api/docs/guides/your-data
- https://developers.openai.com/api/docs/deprecations

Документированы Responses/Chat Completions, context 1050000, output 128000,
reasoning low/medium/high/xhigh/max и Structured Outputs. Датированный snapshot
и объявленная дата shutdown не установлены; требуется повторная проверка lifecycle.
Три режима в capabilities — отключённые предложения настройки, не обещание качества.
Не добавлены вымышленные model IDs или параметры в существующий TaskSpec.

Нужна отдельная проверка обычного/кешированного входа, записи кеша по времени жизни,
reasoning в полном output usage, длинного контекста, tier и региональной надбавки.
Pricing отдельно перечисляет 30m/12h cache write; ставки старого адаптера к Sol
не применимы. Оценка и резерв Sol = null. Текущий полный резерв GPT-4.1 mini сохранён.

Официальный POST /v1/responses/input_tokens считает вход и framing, но передаёт
контекст наружу: необходимы отдельное согласие, exact payload hash и проверка
поддержки schema/model. Он не вызван. Локальный tokenizer/коэффициент символов
не доказаны как граница расходов, резерв не снижен. Rate limits аккаунтные.

Полный Responses reference не удалось получить web tool (страница слишком большая).
Перед адаптером необходимы компактная официальная usage/cache schema, cache control,
проверка reasoning/output cap и отказов JSON Schema. Не выдуманы поля usage.
Сведения о Structured Outputs не заменяют локальную Proposal/SemanticReview проверку.
Отдельная рецензия требует нового task/consent/budget. Store=false не означает ZDR;
retention/cache/регион подтверждает владелец. Ключ Codex/ChatGPT не используется.

Аддитивный unavailable_models в capabilities не является gateway allowlist.
Environment flags не снимают блокировку. HTTP preview/enqueue отвергают Sol,
не резервируя бюджет. Старые задания, UUID, queue/fencing, отмена, ambiguity,
billing #22–23, manual/mock и DOCX остаются в прежних контрактах.

Для включения нужен отдельный проверенный adapter (предпочтительно Responses),
полный финансовый контракт, ключ приложения, штатная сеть и отдельное разрешение
владельца на точный синтетический запрос. Пока эти условия не выполнены, live blocked.
