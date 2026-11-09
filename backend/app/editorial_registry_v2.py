"""Editorial extension v2: proposed diagnostics, not an AI-origin classifier.

Keep the immutable 01–34 source registry unchanged. Coverage is explicit:
an unimplemented rule has status 'insufficient_data', never 'no_issue'.
"""
from types import MappingProxyType

EXTENSION_VERSION = "editorial-proposals-2.0.0"
DIAGNOSTICS = MappingProxyType({
    "35": ("Смысловая избыточность", "lexical_candidate"),
    "36": ("Плотность проверяемых утверждений", "not_implemented"),
    "37": ("Неподкреплённые конкретные сведения", "not_implemented"),
    "38": ("Соответствие вывода доказательствам", "not_implemented"),
    "39": ("Межабзацная связность", "not_implemented"),
    "40": ("Тематическая релевантность", "not_implemented"),
    "41": ("Внутренние противоречия", "not_implemented"),
    "42": ("Повтор содержания в удалённых разделах", "lexical_candidate"),
    "43": ("Смысловое соответствие источнику", "not_implemented"),
    "44": ("Терминологическая согласованность", "not_implemented"),
    "45": ("Межъязыковая точность", "not_implemented"),
    "46": ("Аргументационная глубина", "not_implemented"),
    "47": ("Структурная непрерывность", "not_implemented"),
    "48": ("Происхождение и воспроизводимость", "not_implemented"),
})
