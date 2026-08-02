from flask import Blueprint, current_app, render_template

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


@pages_bp.get("/goals")
def goals():
    return render_template("goals.html", page="goals", title="Накопительные цели")


@pages_bp.get("/people")
def people():
    return render_template("people.html", page="people", title="Саша и Настя")


@pages_bp.get("/settings")
def settings():
    return render_template("settings.html", page="settings", title="Настройки")


@pages_bp.get("/recurring")
def recurring():
    return render_template("recurring.html", page="recurring", title="Регулярные операции")


@pages_bp.get("/insights")
def insights():
    return render_template("insights.html", page="insights", title="Аналитика")


@pages_bp.get("/service-worker.js")
def service_worker():
    response = current_app.send_static_file("service-worker.js")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.mimetype = "application/javascript"
    return response
