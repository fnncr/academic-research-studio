"""One-shot Linux worker. Input/output stay in memory; never logs document data."""
import json
import resource
import sys

resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

from app.extract import extract  # noqa: E402

try:
    result = extract(sys.stdin.buffer.read(10 * 1024 * 1024 + 1), sys.argv[1])
except ValueError as error:
    result = {'error': str(error)}
except Exception:
    result = {'error': 'Не удалось прочитать документ: файл повреждён или имеет неподдерживаемую структуру.'}
sys.stdout.write(json.dumps(result, ensure_ascii=True))
