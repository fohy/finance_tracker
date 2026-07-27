from __future__ import annotations

import csv
import hashlib
import re
import zipfile
from datetime import date, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .db import get_db

MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 5000

HEADER_ALIASES = {
    "date": {"дата", "дата операции", "operation date", "transaction date", "date"},
    "amount": {"сумма", "amount", "transaction amount", "сумма операции"},
    "type": {"тип", "тип операции", "type", "transaction type"},
    "debit": {"дебет", "списание", "расход", "debit", "withdrawal"},
    "credit": {"кредит", "зачисление", "приход", "credit", "deposit"},
    "note": {"описание", "назначение", "комментарий", "детали", "description", "note", "memo"},
    "category": {"категория", "category"},
}


def _normalized_header(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower().replace("ё", "е"))


def _csv_rows(raw: bytes) -> list[list[str]]:
    text = None
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("CSV должен быть в UTF-8 или Windows-1251")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    return [list(row) for row in csv.reader(StringIO(text), dialect) if any(cell.strip() for cell in row)]


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    value = 0
    for char in letters.group(0) if letters else "A":
        value = value * 26 + ord(char) - 64
    return value - 1


def _xlsx_rows(raw: bytes) -> list[list[str]]:
    try:
        archive = zipfile.ZipFile(BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise ValueError("Файл XLSX повреждён") from exc
    names = set(archive.namelist())
    if sum(item.file_size for item in archive.infolist()) > 25 * 1024 * 1024:
        raise ValueError("Распакованный XLSX слишком большой")
    sheet_name = "xl/worksheets/sheet1.xml"
    if "xl/workbook.xml" in names and "xl/_rels/workbook.xml.rels" in names:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = workbook.find(".//{*}sheets/{*}sheet")
        relationship_id = next(
            (value for key, value in first_sheet.attrib.items() if key.endswith("}id")), None
        ) if first_sheet is not None else None
        relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relationship = next(
            (item for item in relationships.findall("{*}Relationship") if item.attrib.get("Id") == relationship_id),
            None,
        )
        if relationship is not None:
            target = relationship.attrib.get("Target", "").lstrip("/")
            sheet_name = target if target.startswith("xl/") else f"xl/{target}"
    if sheet_name not in names:
        candidates = sorted(name for name in names if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
        if not candidates:
            raise ValueError("В XLSX не найден первый лист")
        sheet_name = candidates[0]
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        shared = ["".join(node.itertext()) for node in root.findall("{*}si")]
    root = ElementTree.fromstring(archive.read(sheet_name))
    result: list[list[str]] = []
    for row_node in root.findall(".//{*}sheetData/{*}row"):
        row: list[str] = []
        for cell in row_node.findall("{*}c"):
            index = _column_index(cell.attrib.get("r", "A1"))
            while len(row) <= index:
                row.append("")
            cell_type = cell.attrib.get("t")
            value_node = cell.find("{*}v")
            if cell_type == "inlineStr":
                inline = cell.find("{*}is")
                value = "".join(inline.itertext()) if inline is not None else ""
            else:
                value = value_node.text if value_node is not None and value_node.text else ""
                if cell_type == "s" and value:
                    position = int(value)
                    value = shared[position] if position < len(shared) else ""
            row[index] = value
        if any(str(cell).strip() for cell in row):
            result.append(row)
    return result


def _parse_date(value: str) -> str:
    text = value.strip()
    if re.fullmatch(r"\d+(?:\.0+)?", text):
        serial = int(float(text))
        if 20_000 <= serial <= 80_000:
            return (date(1899, 12, 30) + timedelta(days=serial)).isoformat()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%y"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"неверная дата «{text}»")


def _parse_amount(value: str) -> float:
    text = value.strip().replace("\u00a0", "").replace(" ", "")
    negative = text.startswith("(") and text.endswith(")")
    text = re.sub(r"[^0-9,.-]", "", text.strip("()"))
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "").replace(decimal, ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        amount = float(text)
    except ValueError as exc:
        raise ValueError(f"неверная сумма «{value.strip()}»") from exc
    return -abs(amount) if negative else amount


def parse_statement(filename: str, raw: bytes) -> dict[str, Any]:
    if not raw:
        raise ValueError("Файл пуст")
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError("Файл больше допустимых 5 МБ")
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        source_rows = _csv_rows(raw)
    elif suffix == ".xlsx":
        source_rows = _xlsx_rows(raw)
    else:
        raise ValueError("Поддерживаются только файлы CSV и XLSX")
    if len(source_rows) < 2:
        raise ValueError("В выписке нет строк операций")
    if len(source_rows) - 1 > MAX_IMPORT_ROWS:
        raise ValueError(f"В одном импорте допускается не более {MAX_IMPORT_ROWS} строк")

    canonical: dict[str, int] = {}
    for index, heading in enumerate(source_rows[0]):
        normalized = _normalized_header(heading)
        for key, aliases in HEADER_ALIASES.items():
            if normalized in aliases and key not in canonical:
                canonical[key] = index
    if "date" not in canonical or not ({"amount", "debit", "credit"} & canonical.keys()):
        raise ValueError("Не найдены обязательные колонки: дата и сумма/дебет/кредит")

    def cell(row: list[str], key: str) -> str:
        index = canonical.get(key)
        return str(row[index]).strip() if index is not None and index < len(row) else ""

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for number, source in enumerate(source_rows[1:], start=2):
        try:
            debit, credit = cell(source, "debit"), cell(source, "credit")
            raw_amount = debit or credit or cell(source, "amount")
            amount = _parse_amount(raw_amount)
            raw_type = _normalized_header(cell(source, "type"))
            if debit:
                tx_type = "expense"
            elif credit:
                tx_type = "income"
            elif raw_type in {"income", "credit", "приход", "доход", "зачисление"}:
                tx_type = "income"
            elif raw_type in {"expense", "debit", "расход", "списание"}:
                tx_type = "expense"
            else:
                tx_type = "expense" if amount < 0 else "income"
            if amount == 0:
                raise ValueError("нулевая сумма")
            rows.append({
                "row_number": number,
                "tx_date": _parse_date(cell(source, "date")),
                "tx_type": tx_type,
                "amount": round(abs(amount), 2),
                "note": cell(source, "note"),
                "category": cell(source, "category"),
            })
        except ValueError as exc:
            errors.append({"row_number": number, "error": str(exc)})
    if not rows:
        raise ValueError("Не найдено ни одной корректной операции")
    return {"rows": rows, "errors": errors, "total_rows": len(source_rows) - 1}


def transaction_fingerprint(row: dict[str, Any], account_id: int, person_id: int | None) -> str:
    source = "|".join([
        str(account_id), str(person_id or ""), row["tx_date"], row["tx_type"],
        f"{float(row['amount']):.2f}", str(row.get("note") or "").strip().casefold(),
    ])
    return hashlib.sha256(source.encode()).hexdigest()


def resolve_category(name: str, tx_type: str) -> int | None:
    if not name.strip():
        return None
    rows = get_db().execute("SELECT id, name FROM categories WHERE type = ?", (tx_type,)).fetchall()
    folded = name.strip().casefold()
    match = next((row for row in rows if str(row["name"]).casefold() == folded), None)
    return int(match["id"]) if match else None
