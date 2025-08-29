import asyncio
from collections import defaultdict

# Глобальные переменные для обработки медиа-групп
media_groups = defaultdict(list)
media_group_locks = defaultdict(asyncio.Lock)
document_groups = defaultdict(list)
document_group_locks = defaultdict(asyncio.Lock)