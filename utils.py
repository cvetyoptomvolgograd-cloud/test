import io
import re
from PIL import Image
import pyheif


async def convert_heic_to_jpeg(heic_data: bytes) -> bytes:
    heif_file = pyheif.read(heic_data)
    image = Image.frombytes(
        heif_file.mode,
        heif_file.size,
        heif_file.data,
        "raw",
        heif_file.mode,
        heif_file.stride,
    )

    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='JPEG')
    return img_byte_arr.getvalue()


def parse_composition(text: str):
    composition = []
    color_keywords = ["бел", "розов", "красн", "кремов", "бордов", "лилов", "жёлт", "желт"]

    # Если текст пустой, возвращаем None
    if not text or not text.strip():
        return None

    for line in text.split('\n'):
        if not line.strip():
            continue

        # Парсинг строки
        match = re.match(r'(.+?)[\-\—\:]\s*(\d+)', line.strip())
        if not match:
            continue

        name = match.group(1).strip().lower()
        qty = int(match.group(2))

        # Определение цвета
        color = None
        for c in color_keywords:
            if c in name:
                color = c
                break

        # Определение вида цветка
        kind = "другое"
        if "роза" in name:
            kind = "роза"
        elif "эустом" in name:
            kind = "эустома"
        elif "пион" in name:
            kind = "пион"
        elif "ранункулюс" in name:
            kind = "ранункулюс"
        elif "тюльпан" in name:
            kind = "тюльпан"

        composition.append({
            "raw_name": name,
            "qty": qty,
            "kind": kind,
            "color": color,
            "tags": [kind, f"{kind}:{color}"] if color else [kind]
        })

    # Возвращаем None вместо пустого списка
    return composition if composition else None


def format_price(price_minor: int) -> str:
    # Форматирование цены с пробелами (1 000 ₽)
    price_rub = price_minor // 100
    return f"{price_rub:,} ₽".replace(",", " ")