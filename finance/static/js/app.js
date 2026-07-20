(() => {
    'use strict';

    const state = {
        page: document.body.dataset.page,
        period: 'month',
        anchor: new Date().toISOString().slice(0, 10),
        personId: '',
        bootstrap: null,
        txPage: 1,
    };

    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

    async function api(url, options = {}) {
        const config = { ...options, headers: { ...(options.headers || {}) } };
        if (config.body && typeof config.body !== 'string') {
            config.headers['Content-Type'] = 'application/json';
            config.body = JSON.stringify(config.body);
        }
        const response = await fetch(url, config);
        const result = await response.json().catch(() => ({ ok: false, error: 'Некорректный ответ сервера' }));
        if (!response.ok || !result.ok) throw new Error(result.error || 'Ошибка запроса');
        return result.data;
    }

    function money(value, sign = false) {
        const number = Number(value || 0);
        const prefix = sign && number > 0 ? '+' : '';
        return `${prefix}${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(number)} ₽`;
    }

    function compactMoney(value) {
        return new Intl.NumberFormat('ru-RU', { notation: 'compact', maximumFractionDigits: 1 }).format(Number(value || 0));
    }

    function formatDate(value, options = { day: 'numeric', month: 'short' }) {
        if (!value) return 'Без срока';
        return new Date(`${value}T12:00:00`).toLocaleDateString('ru-RU', options);
    }

    function periodTitle(start, end, period) {
        if (period === 'day') return formatDate(start, { day: 'numeric', month: 'long', year: 'numeric' });
        if (period === 'week') return `${formatDate(start)} — ${formatDate(end, { day: 'numeric', month: 'short', year: 'numeric' })}`;
        return formatDate(start, { month: 'long', year: 'numeric' });
    }

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#039;', '"': '&quot;' }[ch]));
    }

    function toast(message, type = 'success') {
        const node = document.createElement('div');
        node.className = `toast ${type}`;
        node.textContent = message;
        $('#toastStack').appendChild(node);
        setTimeout(() => node.remove(), 3500);
    }

    function openModal(id) {
        const modal = document.getElementById(id);
        modal?.classList.add('open');
        modal?.setAttribute('aria-hidden', 'false');
    }

    function closeModals() {
        $$('.modal-backdrop').forEach(modal => {
            modal.classList.remove('open');
            modal.setAttribute('aria-hidden', 'true');
        });
    }

    function personOptions(includeAll = false) {
        const head = includeAll ? '<option value="">Все вместе</option>' : '<option value="">Общее</option>';
        return head + state.bootstrap.people.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
    }

    function accountOptions(kind = null) {
        return state.bootstrap.accounts
            .filter(a => !kind || a.kind === kind)
            .map(a => `<option value="${a.id}">${escapeHtml(a.name)} · ${money(a.balance)}</option>`).join('');
    }

    function categoryOptions(type) {
        return state.bootstrap.categories
            .filter(c => c.type === type)
            .map(c => `<option value="${c.id}">${escapeHtml(c.icon)} ${escapeHtml(c.name)}</option>`).join('');
    }

    function setupTransactionModal() {
        const form = $('#transactionForm');
        if (!form) return;
        form.tx_date.value = state.bootstrap.today;
        form.person_id.innerHTML = personOptions(false);
        form.account_id.innerHTML = accountOptions();
        form.target_account_id.innerHTML = accountOptions('investment');

        const setType = type => {
            form.tx_type.value = type;
            $$('[data-tx-type]', form).forEach(btn => btn.classList.toggle('active', btn.dataset.txType === type));
            const categoryField = $('#categoryField');
            const targetField = $('#targetAccountField');
            if (type === 'transfer') {
                categoryField.classList.add('hidden');
                targetField.classList.remove('hidden');
                form.category_id.required = false;
                form.target_account_id.required = true;
                form.account_id.innerHTML = accountOptions('life');
            } else {
                categoryField.classList.remove('hidden');
                targetField.classList.add('hidden');
                form.category_id.required = true;
                form.target_account_id.required = false;
                form.category_id.innerHTML = categoryOptions(type);
                form.account_id.innerHTML = accountOptions('life');
            }
        };

        $$('[data-tx-type]', form).forEach(btn => btn.addEventListener('click', () => setType(btn.dataset.txType)));
        $$('[data-open-transaction]').forEach(btn => btn.addEventListener('click', () => {
            setType(btn.dataset.defaultType || 'expense');
            openModal('transactionModal');
        }));
        $$('[data-close-modal]').forEach(btn => btn.addEventListener('click', closeModals));
        $$('.modal-backdrop').forEach(modal => modal.addEventListener('click', event => {
            if (event.target === modal) closeModals();
        }));
        document.addEventListener('keydown', event => { if (event.key === 'Escape') closeModals(); });

        form.addEventListener('submit', async event => {
            event.preventDefault();
            const data = Object.fromEntries(new FormData(form).entries());
            try {
                await api('/api/transactions', { method: 'POST', body: data });
                toast('Операция сохранена');
                closeModals();
                form.reset();
                form.tx_date.value = state.bootstrap.today;
                await refreshBootstrap();
                await loadCurrentPage();
            } catch (error) { toast(error.message, 'error'); }
        });
    }

    function setupNavigation() {
        $('#mobileMenu')?.addEventListener('click', () => $('#sidebar')?.classList.toggle('open'));
        $$('[data-period]').forEach(button => button.addEventListener('click', () => {
            state.period = button.dataset.period;
            state.txPage = 1;
            $$('[data-period]').forEach(b => b.classList.toggle('active', b === button));
            loadCurrentPage();
        }));
        $$('[data-period-nav]').forEach(button => button.addEventListener('click', async () => {
            const direction = button.dataset.periodNav === 'prev' ? -1 : 1;
            const summary = await api(`/api/summary?period=${state.period}&anchor=${state.anchor}`);
            state.anchor = direction < 0 ? summary.prev_anchor : summary.next_anchor;
            state.txPage = 1;
            loadCurrentPage();
        }));
        $('#personFilter')?.addEventListener('change', event => {
            state.personId = event.target.value;
            state.txPage = 1;
            loadCurrentPage();
        });
    }

    function setPeriodLabel(data) {
        const node = $('#periodLabel');
        if (node) node.textContent = periodTitle(data.start, data.end, state.period);
    }

    function deltaText(value, inverse = false) {
        const number = Number(value || 0);
        const positive = inverse ? number <= 0 : number >= 0;
        return { text: `${number >= 0 ? '+' : ''}${number.toFixed(1)}% к прошлому периоду`, className: positive ? 'positive' : 'negative' };
    }

    function setDelta(id, value, inverse = false) {
        const node = document.getElementById(id);
        if (!node) return;
        const result = deltaText(value, inverse);
        node.textContent = result.text;
        node.className = result.className;
    }

    function transactionRow(item) {
        const names = { income: 'Доход', expense: 'Расход', transfer: 'В инвестиции', interest: 'Начисление процентов' };
        const icon = item.category_icon || ({ transfer: '↗', interest: '％' }[item.tx_type] || '•');
        const title = item.category_name || names[item.tx_type];
        const amountPrefix = item.tx_type === 'income' || item.tx_type === 'interest' ? '+' : item.tx_type === 'expense' ? '−' : '';
        return `<div class="transaction-row">
            <div class="tx-icon" style="color:${escapeHtml(item.category_color || '#9b87ff')}">${escapeHtml(icon)}</div>
            <div class="tx-main"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(item.person_name || 'Общее')} · ${formatDate(item.tx_date)}${item.note ? ` · ${escapeHtml(item.note)}` : ''}</span></div>
            <div class="tx-amount ${item.tx_type}">${amountPrefix}${money(item.amount)}</div>
        </div>`;
    }

    function drawLineChart(container, rows, keys = ['income', 'expense', 'invested']) {
        if (!container) return;
        if (!rows.length) {
            container.innerHTML = '<div class="chart-empty">За выбранный период пока нет данных</div>';
            return;
        }
        const width = 900, height = 280, left = 45, right = 18, top = 18, bottom = 35;
        const maxValue = Math.max(1, ...rows.flatMap(row => keys.map(key => Number(row[key] || 0))));
        const x = index => left + (rows.length === 1 ? (width - left - right) / 2 : index * (width - left - right) / (rows.length - 1));
        const y = value => top + (height - top - bottom) * (1 - Number(value || 0) / maxValue);
        const path = key => rows.map((row, index) => `${index ? 'L' : 'M'} ${x(index).toFixed(1)} ${y(row[key]).toFixed(1)}`).join(' ');
        const grid = [0, .25, .5, .75, 1].map(part => {
            const yy = top + (height - top - bottom) * part;
            const label = compactMoney(maxValue * (1 - part));
            return `<line class="svg-grid" x1="${left}" y1="${yy}" x2="${width-right}" y2="${yy}"/><text x="0" y="${yy+4}">${label}</text>`;
        }).join('');
        const labels = rows.map((row, index) => {
            if (rows.length > 12 && index % Math.ceil(rows.length / 8) !== 0 && index !== rows.length - 1) return '';
            const label = /^\d{4}-\d{2}-\d{2}$/.test(String(row.label)) ? formatDate(row.label, { day: 'numeric', month: 'short' }) : String(row.label);
            return `<text text-anchor="middle" x="${x(index)}" y="${height-8}">${escapeHtml(label)}</text>`;
        }).join('');
        container.innerHTML = `<svg class="svg-chart" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">${grid}<path class="svg-income" d="${path(keys[0])}"/><path class="svg-expense" d="${path(keys[1])}"/>${keys[2] ? `<path class="svg-invested" d="${path(keys[2])}"/>` : ''}${labels}</svg>`;
    }

    async function loadDashboard() {
        const query = new URLSearchParams({ period: state.period, anchor: state.anchor });
        if (state.personId) query.set('person_id', state.personId);
        const [data, tx] = await Promise.all([
            api(`/api/summary?${query}`),
            api(`/api/transactions?${query}&per_page=6`),
        ]);
        setPeriodLabel(data);
        const current = data.current;
        $('#lifeBalance').textContent = money(data.life_balance);
        $('#investmentBalance').textContent = money(data.investment_balance);
        $('#totalCapital').textContent = money(data.life_balance + data.investment_balance);
        $('#capitalTrend').textContent = `${data.score.savings_rate >= 0 ? '+' : ''}${data.score.savings_rate}% сбережений`;
        $('#metricIncome').textContent = money(current.income);
        $('#metricExpense').textContent = money(current.expense);
        $('#metricNet').textContent = money(current.net, true);
        $('#metricInvested').textContent = money(current.invested);
        setDelta('deltaIncome', data.delta.income);
        setDelta('deltaExpense', data.delta.expense, true);
        setDelta('deltaNet', data.delta.net);
        setDelta('deltaInvested', data.delta.invested);
        $('#scoreValue').textContent = data.score.value;
        $('#scoreLabel').textContent = data.score.label;
        $('#scoreTip').textContent = data.score.tips[0];
        $('#scoreRing').style.setProperty('--score', `${data.score.value * 3.6}deg`);
        $('#forecastIncome').textContent = money(data.forecast.income);
        $('#forecastExpense').textContent = money(data.forecast.expense);
        $('#forecastNet').textContent = money(data.forecast.net, true);
        $('#forecastInvested').textContent = money(data.forecast.invested);
        drawLineChart($('#trendChart'), data.trend);
        renderCategories(data.breakdown);
        $('#recentTransactions').innerHTML = tx.items.length ? tx.items.map(transactionRow).join('') : '<div class="empty-state">Операций за период нет</div>';
    }

    function renderCategories(items) {
        const container = $('#categoryBreakdown');
        if (!container) return;
        if (!items.length) { container.innerHTML = '<div class="empty-state">Расходов пока нет</div>'; return; }
        const total = items.reduce((sum, item) => sum + Number(item.amount), 0);
        container.innerHTML = items.slice(0, 7).map(item => {
            const pct = total ? Number(item.amount) / total * 100 : 0;
            return `<div class="category-row" style="--cat-color:${escapeHtml(item.color)}">
                <div class="category-icon">${escapeHtml(item.icon)}</div>
                <div><div class="category-name"><span>${escapeHtml(item.name)}</span><span>${pct.toFixed(0)}%</span></div><div class="progress-track"><i style="width:${pct}%"></i></div></div>
                <strong>${money(item.amount)}</strong>
            </div>`;
        }).join('');
    }

    async function loadTransactions() {
        const query = new URLSearchParams({ period: state.period, anchor: state.anchor, page: state.txPage, per_page: 20 });
        if (state.personId) query.set('person_id', state.personId);
        const type = $('#txTypeFilter')?.value;
        if (type) query.set('type', type);
        const [summary, data] = await Promise.all([api(`/api/summary?${query}`), api(`/api/transactions?${query}`)]);
        setPeriodLabel(summary);
        const tbody = $('#transactionsTable');
        tbody.innerHTML = data.items.length ? data.items.map(item => {
            const names = { income: 'Доход', expense: 'Расход', transfer: 'Перевод', interest: 'Проценты' };
            const prefix = ['income', 'interest'].includes(item.tx_type) ? '+' : item.tx_type === 'expense' ? '−' : '';
            return `<tr>
                <td>${formatDate(item.tx_date, { day: '2-digit', month: '2-digit', year: 'numeric' })}</td>
                <td><div class="table-main"><div class="tx-icon">${escapeHtml(item.category_icon || (item.tx_type === 'interest' ? '％' : '↗'))}</div><div><strong>${names[item.tx_type]}</strong><div class="subtext">${escapeHtml(item.category_name || 'Без категории')}</div></div></div></td>
                <td><strong>${escapeHtml(item.category_name || (item.tx_type === 'transfer' ? 'Инвестиции' : 'Автоначисление'))}</strong><div class="subtext">${escapeHtml(item.note || 'Без пометки')}</div></td>
                <td>${item.person_name ? `<span class="person-pill" style="--avatar:${escapeHtml(item.avatar_color)}"><i>${escapeHtml(item.person_name[0])}</i>${escapeHtml(item.person_name)}</span>` : '—'}</td>
                <td>${escapeHtml(item.account_name || '—')}${item.target_account_name ? `<div class="subtext">→ ${escapeHtml(item.target_account_name)}</div>` : ''}</td>
                <td class="align-right"><strong class="tx-amount ${item.tx_type}">${prefix}${money(item.amount)}</strong></td>
                <td>${item.tx_type !== 'interest' ? `<button class="delete-btn" data-delete-tx="${item.id}" title="Удалить">×</button>` : ''}</td>
            </tr>`;
        }).join('') : '<tr><td colspan="7"><div class="empty-state">За этот период операций нет</div></td></tr>';
        $$('[data-delete-tx]').forEach(btn => btn.addEventListener('click', () => deleteTransaction(btn.dataset.deleteTx)));
        renderPagination(data);
    }

    function renderPagination(data) {
        const container = $('#transactionsPagination');
        if (!container) return;
        container.innerHTML = Array.from({ length: data.pages }, (_, i) => i + 1).map(page => `<button class="${page === data.page ? 'active' : ''}" data-page="${page}">${page}</button>`).join('');
        $$('[data-page]', container).forEach(button => button.addEventListener('click', () => { state.txPage = Number(button.dataset.page); loadTransactions(); }));
    }

    async function deleteTransaction(id) {
        if (!confirm('Удалить операцию и пересчитать баланс?')) return;
        try {
            await api(`/api/transactions/${id}`, { method: 'DELETE' });
            toast('Операция удалена');
            await refreshBootstrap();
            loadTransactions();
        } catch (error) { toast(error.message, 'error'); }
    }

    function openEntityForm(title, body, onSubmit) {
        const container = $('#entityModalContent');
        container.innerHTML = `<div class="modal-head"><div><div class="eyebrow">FinFlow</div><h2>${escapeHtml(title)}</h2></div><button class="icon-btn" data-close-entity>×</button></div><form id="entityForm" class="stack-form">${body}<div class="modal-actions"><button type="button" class="btn btn-ghost" data-close-entity>Отмена</button><button type="submit" class="btn btn-primary">Сохранить</button></div></form>`;
        $$('[data-close-entity]', container).forEach(btn => btn.addEventListener('click', closeModals));
        $('#entityForm', container).addEventListener('submit', async event => {
            event.preventDefault();
            await onSubmit(Object.fromEntries(new FormData(event.target).entries()));
        });
        openModal('entityModal');
    }

    function openCategoryForm() {
        openEntityForm('Новая категория', `
            <label>Название<input name="name" required placeholder="Например: питомцы"></label>
            <label>Тип<select name="type"><option value="expense">Расход</option><option value="income">Доход</option></select></label>
            <label>Иконка<input name="icon" maxlength="3" value="•"></label>
            <label>Цвет<input name="color" type="color" value="#7c5cff"></label>`, async data => {
            try {
                await api('/api/categories', { method: 'POST', body: data });
                toast('Категория добавлена'); closeModals(); await refreshBootstrap();
            } catch (error) { toast(error.message, 'error'); }
        });
    }

    async function loadInvestments() {
        const [accounts, tx] = await Promise.all([
            api('/api/accounts'),
            api('/api/transactions?period=month&anchor=' + state.anchor + '&per_page=20'),
        ]);
        const investments = accounts.filter(a => a.kind === 'investment');
        $('#investmentAccounts').innerHTML = investments.map(account => `<article class="card account-card"><div class="card-kicker">${escapeHtml(account.name)}</div><strong>${money(account.balance)}</strong><div class="account-meta"><span>${Number(account.annual_rate).toFixed(1)}% годовых</span><span>начислено по ${formatDate(account.last_accrual_date)}</span></div></article>`).join('');
        $('#investmentTransactions').innerHTML = tx.items.filter(item => ['transfer', 'interest'].includes(item.tx_type)).map(transactionRow).join('') || '<div class="empty-state">Пополнений пока нет</div>';
        setupInvestmentCalculator(investments[0]);
    }

    function setupInvestmentCalculator(account) {
        const form = $('#investmentCalculator');
        if (!form || form.dataset.ready) return;
        form.dataset.ready = '1';
        if (account) form.rate.value = account.annual_rate;
        const calculate = () => {
            const principal = Number(account?.balance || 0);
            const monthly = Number(form.monthly.value || 0);
            const years = Number(form.years.value || 1);
            const annual = Number(form.rate.value || 0) / 100;
            const rate = annual / 12;
            const months = years * 12;
            let value = principal;
            const series = [];
            for (let i = 0; i <= months; i++) {
                if (i > 0) value = value * (1 + rate) + monthly;
                if (i % Math.max(1, Math.round(months / 24)) === 0 || i === months) series.push({ label: `${i} мес`, income: value, expense: 0 });
            }
            $('#futureValue').textContent = money(value);
            drawLineChart($('#investmentProjection'), series, ['income', 'expense', null]);
        };
        form.addEventListener('input', calculate);
        calculate();
    }

    async function loadPurchases() {
        const data = await api('/api/purchases');
        $('#availableForPurchases').textContent = money(data.available_monthly);
        const labels = { safe: 'Безопасный темп', tight: 'Потребуется дисциплина', risk: 'Вредит инвестиционному плану' };
        $('#purchaseGrid').innerHTML = data.items.length ? data.items.map(item => `<article class="card entity-card">
            <div class="entity-top"><div class="entity-title"><div class="card-kicker">Покупка · ${escapeHtml(item.person_name || 'Общая')}</div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.note || 'Без заметки')}</p></div><span class="priority ${item.priority}">${item.priority}</span></div>
            <div class="entity-amount">${money(item.cost)}</div>
            <div class="entity-progress"><div class="meta"><span>Накоплено ${money(item.saved_amount)}</span><span>${item.progress}%</span></div><div class="progress-track"><i style="width:${item.progress}%;background:var(--green)"></i></div></div>
            <div class="entity-stats"><div><span>В день</span><strong>${money(item.daily_save)}</strong></div><div><span>В неделю</span><strong>${money(item.weekly_save)}</strong></div><div><span>В месяц</span><strong>${money(item.monthly_save)}</strong></div><div><span>До срока</span><strong>${item.days_left} дн.</strong></div></div>
            <div class="affordability ${item.affordability}">● ${labels[item.affordability]}</div>
            <div class="entity-footer"><button class="btn btn-secondary" data-fund-purchase="${item.id}" data-current="${item.saved_amount}">Пополнить</button><button class="btn btn-ghost" data-delete-purchase="${item.id}">Удалить</button></div>
        </article>`).join('') : '<div class="card empty-state">Добавьте первую запланированную покупку</div>';
        $$('[data-fund-purchase]').forEach(btn => btn.addEventListener('click', () => fundEntity('purchases', btn.dataset.fundPurchase, Number(btn.dataset.current), loadPurchases)));
        $$('[data-delete-purchase]').forEach(btn => btn.addEventListener('click', () => deleteEntity('purchases', btn.dataset.deletePurchase, loadPurchases)));
    }

    function openPurchaseForm() {
        openEntityForm('Новая покупка', `
            <label>Название<input name="title" required placeholder="Например: новый ноутбук"></label>
            <label>Стоимость<input name="cost" type="number" min="1" required></label>
            <label>Уже накоплено<input name="saved_amount" type="number" min="0" value="0"></label>
            <label>Желаемая дата<input name="target_date" type="date"></label>
            <label>Для кого<select name="person_id">${personOptions(false)}</select></label>
            <label>Приоритет<select name="priority"><option value="high">Высокий</option><option value="medium" selected>Средний</option><option value="low">Низкий</option></select></label>
            <label>Пометка<textarea name="note" rows="3"></textarea></label>`, async data => {
            try { await api('/api/purchases', { method: 'POST', body: data }); toast('Покупка добавлена'); closeModals(); loadPurchases(); }
            catch (error) { toast(error.message, 'error'); }
        });
    }

    async function loadGoals() {
        const data = await api('/api/goals');
        $('#goalsGrid').innerHTML = data.length ? data.map(item => `<article class="card entity-card">
            <div class="entity-top"><div class="entity-title"><div class="card-kicker">Цель · ${escapeHtml(item.person_name || 'Общая')}</div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.note || 'Без заметки')}</p></div><span class="priority ${item.priority}">${item.priority}</span></div>
            <div class="entity-amount">${money(item.target_amount)}</div>
            <div class="entity-progress"><div class="meta"><span>Достигнуто ${money(item.current_amount)}</span><span>${item.progress}%</span></div><div class="progress-track"><i style="width:${item.progress}%;background:var(--primary)"></i></div></div>
            <div class="entity-stats"><div><span>Осталось</span><strong>${money(item.remaining)}</strong></div><div><span>Нужно в месяц</span><strong>${money(item.monthly_needed)}</strong></div><div><span>Срок</span><strong>${formatDate(item.target_date)}</strong></div><div><span>До цели</span><strong>${item.days_left} дн.</strong></div></div>
            <div class="entity-footer"><button class="btn btn-secondary" data-fund-goal="${item.id}" data-current="${item.current_amount}">Добавить прогресс</button><button class="btn btn-ghost" data-delete-goal="${item.id}">Удалить</button></div>
        </article>`).join('') : '<div class="card empty-state">Создайте первую финансовую цель</div>';
        $$('[data-fund-goal]').forEach(btn => btn.addEventListener('click', () => fundEntity('goals', btn.dataset.fundGoal, Number(btn.dataset.current), loadGoals, 'current_amount')));
        $$('[data-delete-goal]').forEach(btn => btn.addEventListener('click', () => deleteEntity('goals', btn.dataset.deleteGoal, loadGoals)));
    }

    function openGoalForm() {
        openEntityForm('Новая цель', `
            <label>Название<input name="title" required placeholder="Например: финансовая подушка"></label>
            <label>Целевая сумма<input name="target_amount" type="number" min="1" required></label>
            <label>Уже накоплено<input name="current_amount" type="number" min="0" value="0"></label>
            <label>Срок<input name="target_date" type="date"></label>
            <label>Чья цель<select name="person_id">${personOptions(false)}</select></label>
            <label>Приоритет<select name="priority"><option value="high">Высокий</option><option value="medium" selected>Средний</option><option value="low">Низкий</option></select></label>
            <label>Описание<textarea name="note" rows="3"></textarea></label>`, async data => {
            try { await api('/api/goals', { method: 'POST', body: data }); toast('Цель создана'); closeModals(); loadGoals(); }
            catch (error) { toast(error.message, 'error'); }
        });
    }

    async function fundEntity(resource, id, current, reload, field = 'saved_amount') {
        const amount = Number(prompt('Сколько добавить?', '10000'));
        if (!amount || amount <= 0) return;
        try { await api(`/api/${resource}/${id}`, { method: 'PATCH', body: { [field]: current + amount } }); toast('Прогресс обновлён'); reload(); }
        catch (error) { toast(error.message, 'error'); }
    }

    async function deleteEntity(resource, id, reload) {
        if (!confirm('Удалить запись?')) return;
        try { await api(`/api/${resource}/${id}`, { method: 'DELETE' }); toast('Запись удалена'); reload(); }
        catch (error) { toast(error.message, 'error'); }
    }

    async function loadPeople() {
        const query = new URLSearchParams({ period: state.period, anchor: state.anchor });
        const data = await api(`/api/people-metrics?${query}`);
        if (data[0]) setPeriodLabel(data[0]);
        $('#peopleMetrics').innerHTML = data.map(item => {
            const p = item.person, m = item.current;
            return `<article class="card person-card" style="--avatar:${escapeHtml(p.avatar_color)}">
                <div class="person-head"><div class="big-avatar">${escapeHtml(p.name[0])}</div><div><h3>${escapeHtml(p.name)}</h3><span>Персональная статистика за период</span></div></div>
                <div class="person-metrics"><div><span>Доход</span><strong class="tx-amount income">${money(m.income)}</strong></div><div><span>Расход</span><strong class="tx-amount expense">${money(m.expense)}</strong></div><div><span>Инвестиции</span><strong class="tx-amount transfer">${money(m.invested)}</strong></div></div>
                <div class="mini-score"><div><div class="card-kicker">Индекс действий</div><strong>${item.score.value}/100</strong></div><span class="priority ${item.score.tone === 'good' ? 'low' : item.score.tone === 'bad' ? 'high' : 'medium'}">${escapeHtml(item.score.label)}</span></div>
                <div style="margin-top:18px"><div class="card-kicker" style="margin-bottom:12px">Главные категории расходов</div>${item.breakdown.slice(0,4).map(cat => `<div class="category-name"><span>${escapeHtml(cat.icon)} ${escapeHtml(cat.name)}</span><strong>${money(cat.amount)}</strong></div>`).join('') || '<div class="muted">Нет расходов</div>'}</div>
            </article>`;
        }).join('');
    }

    async function loadSettings() {
        const data = await api('/api/settings');
        const form = $('#settingsForm');
        Object.entries(data).forEach(([key, value]) => { if (form.elements[key]) form.elements[key].value = value; });
        if (!form.dataset.ready) {
            form.dataset.ready = '1';
            form.addEventListener('submit', async event => {
                event.preventDefault();
                try { await api('/api/settings', { method: 'PUT', body: Object.fromEntries(new FormData(form).entries()) }); toast('Настройки сохранены'); }
                catch (error) { toast(error.message, 'error'); }
            });
        }
    }

    async function refreshBootstrap() {
        state.bootstrap = await api('/api/bootstrap');
        state.anchor ||= state.bootstrap.today;
        const filter = $('#personFilter');
        if (filter) {
            const previous = filter.value;
            filter.innerHTML = personOptions(true);
            filter.value = previous;
        }
        const form = $('#transactionForm');
        if (form) {
            form.person_id.innerHTML = personOptions(false);
            form.account_id.innerHTML = accountOptions();
            form.target_account_id.innerHTML = accountOptions('investment');
            form.category_id.innerHTML = categoryOptions(form.tx_type.value || 'expense');
        }
    }

    async function loadCurrentPage() {
        try {
            const loaders = {
                dashboard: loadDashboard,
                transactions: loadTransactions,
                investments: loadInvestments,
                purchases: loadPurchases,
                goals: loadGoals,
                people: loadPeople,
                settings: loadSettings,
            };
            await loaders[state.page]?.();
        } catch (error) {
            console.error(error);
            toast(error.message, 'error');
        }
    }

    async function init() {
        try {
            await refreshBootstrap();
            state.anchor = state.bootstrap.today;
            setupNavigation();
            setupTransactionModal();
            $('#txTypeFilter')?.addEventListener('change', () => { state.txPage = 1; loadTransactions(); });
            $('#addCategoryBtn')?.addEventListener('click', openCategoryForm);
            $('#addPurchaseBtn')?.addEventListener('click', openPurchaseForm);
            $('#addGoalBtn')?.addEventListener('click', openGoalForm);
            await loadCurrentPage();
        } catch (error) {
            console.error(error);
            toast(`Не удалось запустить приложение: ${error.message}`, 'error');
        }
    }

    init();
})();
