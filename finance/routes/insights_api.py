from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

from ..insights_service import financial_cushion, spending_anomalies, weekly_report, what_if

insights_api_bp = Blueprint("insights_api", __name__)


def ok(data: Any = None):
    return jsonify({"ok": True, "data": data})


@insights_api_bp.errorhandler(ValueError)
def value_error(error: ValueError):
    return jsonify({"ok": False, "error": str(error)}), 400


@insights_api_bp.get("/insights")
def insights():
    return ok({"cushion": financial_cushion(), "anomalies": spending_anomalies()})


@insights_api_bp.get("/insights/anomalies")
def anomalies():
    return ok(spending_anomalies())


@insights_api_bp.post("/insights/what-if")
def scenario():
    return ok(what_if(request.get_json(silent=True) or {}))


@insights_api_bp.get("/weekly-report")
def report():
    return ok(weekly_report())
