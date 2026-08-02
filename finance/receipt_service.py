from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException as CurlRequestException

REQUIRED_QR_FIELDS = ("t", "s", "fn", "i", "fp", "n")
PROVERKACHEKA_URL = "https://proverkacheka.com/api/v1/check/get"

CATEGORY_KEYWORDS = {
    "Алкоголь": (
        "пиво", "водка", "вино", "коньяк", "виски", "сидр", "ром ", "джин ",
        "шампан", "вермут", "ликер", "ликёр", "алког",
    ),
    "Дом и быт": (
        "туалетн", "бумага", "салфет", "губк", "порошок", "кондиционер для белья",
        "средство для", "чистящ", "моющ", "мусорн", "пакеты для мусора", "освежитель",
        "мыло", "лампоч", "батарейк", "полотенц", "посуда",
    ),
    "Продукты": (
        "арбуз", "молоко", "хлеб", "батон", "сыр", "масло слив", "яйц", "мясо",
        "куриц", "рыб", "овощ", "фрукт", "яблок", "банан", "картоф", "томат",
        "огур", "колбас", "макарон", "круп", "рис ", "греч", "кефир", "творог",
        "сметан", "йогурт", "сахар", "соль", "мука", "чай ", "кофе",
    ),
    "Приколюхи": (
        "шоколад", "жвач", "жеватель", "конфет", "мармелад", "чипс", "сухарик",
        "печенье", "пирожн", "морожен", "газирован", "энергетик", "игруш",
    ),
}


def parse_receipt_qr(raw_value: Any) -> dict[str, Any]:
    """Parse the standard Russian fiscal receipt QR payload without a network call."""
    raw = str(raw_value or "").strip()
    if not raw:
        raise ValueError("Отсканируйте QR-код или вставьте строку из него")

    # Some scanners return an URL whose query contains the fiscal payload.
    query = urlparse(raw).query if "://" in raw else raw.lstrip("?")
    values = {key.lower(): items[-1] for key, items in parse_qs(query).items() if items}
    missing = [key for key in REQUIRED_QR_FIELDS if not values.get(key)]
    if missing:
        raise ValueError("Это не QR-код кассового чека: не хватает реквизитов " + ", ".join(missing))

    try:
        amount = Decimal(values["s"].replace(",", ".")).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise ValueError("В QR-коде указана некорректная сумма") from exc
    if amount <= 0:
        raise ValueError("Сумма чека должна быть больше нуля")

    timestamp = _parse_fiscal_time(values["t"])
    operation = int(values["n"])
    if operation not in {1, 2, 3, 4}:
        raise ValueError("Неизвестный тип расчёта в QR-коде")

    return {
        "raw": raw,
        "amount": float(amount),
        "date": timestamp.date().isoformat(),
        "time": timestamp.strftime("%H:%M"),
        "fiscal_drive": values["fn"],
        "fiscal_document": values["i"],
        "fiscal_sign": values["fp"],
        "operation": operation,
        "is_expense": operation in {1, 3},
        "note": f"Чек ФН {values['fn']}, ФД {values['i']}",
    }


def fetch_receipt(raw_value: Any, token: str) -> dict[str, Any]:
    receipt = parse_receipt_qr(raw_value)
    if not token:
        raise ValueError("Не настроен токен ProverkaCheka. Добавьте PROVERKACHEKA_TOKEN в файл .env")
    qr = parse_qs(urlparse(receipt["raw"]).query if "://" in receipt["raw"] else receipt["raw"])
    form = {
        "fn": qr["fn"][-1], "fd": qr["i"][-1], "fp": qr["fp"][-1],
        "t": qr["t"][-1], "n": qr["n"][-1], "s": qr["s"][-1],
        "qr": "1", "token": token,
    }
    try:
        response = requests.post(
            PROVERKACHEKA_URL,
            data=urlencode(form),
            headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "FinFlow/0.1"},
            timeout=20,
        )
        response.raise_for_status()
        result = response.json()
    except (CurlRequestException, json.JSONDecodeError) as exc:
        raise ValueError("Не удалось получить состав чека из ProverkaCheka") from exc
    if int(result.get("code", 0)) != 1:
        detail = result.get("text") or result.get("message")
        if not detail and isinstance(result.get("data"), str):
            detail = result["data"]
        if int(result.get("code", 0)) == 4:
            detail = f"{detail or 'Чек поставлен в очередь'} Попробуйте снова через несколько минут."
        raise ValueError(str(detail or "Чек пока не найден в ProverkaCheka"))
    fiscal = result.get("data", {}).get("json", {})
    items = fiscal.get("items") or []
    if not items:
        raise ValueError("ProverkaCheka вернул чек без товарных позиций")
    receipt["merchant"] = str(fiscal.get("user") or fiscal.get("retailPlace") or "Магазин")
    raw_total = sum(float(item.get("sum") or 0) for item in items)
    values_are_kopecks = abs(raw_total / 100 - receipt["amount"]) < abs(raw_total - receipt["amount"])
    receipt["items"] = [_normalise_item(item, values_are_kopecks) for item in items]
    return receipt


def _normalise_item(item: dict[str, Any], values_are_kopecks: bool) -> dict[str, Any]:
    name = str(item.get("name") or "Товар").strip()
    raw_sum = float(item.get("sum") or 0)
    # ФФД обычно передаёт деньги в копейках; некоторые прокси уже переводят в рубли.
    amount = raw_sum / 100 if values_are_kopecks else raw_sum
    category, confidence = classify_item(name)
    return {
        "name": name,
        "amount": round(amount, 2),
        "category_name": category,
        "confidence": confidence,
    }


def classify_item(name: str) -> tuple[str | None, str]:
    value = normalise_product_name(name)
    matches = [category for category, words in CATEGORY_KEYWORDS.items() if any(word.replace("ё", "е") in value for word in words)]
    if len(matches) == 1:
        return matches[0], "high"
    return None, "uncertain"


def normalise_product_name(name: str) -> str:
    value = str(name).casefold().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return " ".join(value.split())[:300]


def _parse_fiscal_time(value: str) -> datetime:
    cleaned = re.sub(r"[^0-9T]", "", value)
    has_separator = "T" in cleaned
    digits = cleaned.replace("T", "")
    if len(digits) == 12:
        patterns = ("%Y%m%dT%H%M",) if has_separator else ("%Y%m%d%H%M",)
    elif len(digits) == 14:
        patterns = ("%Y%m%dT%H%M%S",) if has_separator else ("%Y%m%d%H%M%S",)
    else:
        patterns = ()
    for pattern in patterns:
        try:
            return datetime.strptime(cleaned, pattern)
        except ValueError:
            continue
    raise ValueError("В QR-коде указана некорректная дата чека")
