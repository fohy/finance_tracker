from flask import Blueprint, render_template

pages_bp = Blueprint("pages", __name__)


@pages_bp.get("/")
def dashboard():
    return render_template("dashboard.html", page="dashboard", title="Обзор")


@pages_bp.get("/transactions")
def transactions():
    return render_template("transactions.html", page="transactions", title="Операции")


@pages_bp.get("/investments")
def investments():
    return render_template("investments.html", page="investments", title="Инвестиции")


@pages_bp.get("/purchases")
def purchases():
    return render_template("purchases.html", page="purchases", title="План покупок")


@pages_bp.get("/goals")
def goals():
    return render_template("goals.html", page="goals", title="Цели")


@pages_bp.get("/people")
def people():
    return render_template("people.html", page="people", title="Саша и Настя")


@pages_bp.get("/settings")
def settings():
    return render_template("settings.html", page="settings", title="Настройки")
