(() => {
    'use strict';

    const state = {
        page: document.body.dataset.page,
        period: 'month',
        anchor: new Date().toISOString().slice(0, 10),
        personId: '',
        bootstrap: null,
        txPage: 1,
        lastFocused: null,
    };

    const $ = (selector, root = document) => root.querySelector(selector);
    const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
    const iconsUrl = document.querySelector('meta[name="icons-url"]')?.content || '/static/icons.svg';
    const themeStorageKey = 'finflow-theme';
    const iconKeys = new Set([
        'category', 'wallet', 'briefcase', 'gift', 'refund', 'groceries', 'cafe',
        'transport', 'housing', 'utilities', 'health', 'clothing', 'entertainment',
        'education', 'subscriptions', 'aid', 'travel', 'home-care', 'beauty',
        'internet', 'alert', 'car', 'fitness', 'children', 'pets', 'devices',
        'repair', 'taxes', 'insurance', 'hobby', 'charity', 'transactions',
        'trend', 'interest', 'edit', 'copy', 'trash', 'close', 'target',
        'account-checking', 'account-cash', 'account-savings', 'account-deposit',
        'account-currency', 'account-investment', 'allocation-spending',
        'allocation-savings', 'allocation-currency',
    ]);

    function iconSvg(key, className = 'icon') {
        const safeKey = iconKeys.has(String(key)) ? String(key) : 'category';
        return `<svg class="${className}" aria-hidden="true"><use href="${iconsUrl}#icon-${safeKey}"></use></svg>`;
    }

    const customSelectRegistry = new Map();
    let activeCustomSelect = null;

    function selectLabel(select) {
        const explicit = select.getAttribute('aria-label');
        if (explicit) return explicit;
        const label = select.closest('label');
        const text = label ? [...label.childNodes].find(node => node.nodeType === Node.TEXT_NODE)?.textContent?.trim() : '';
        return text || 'Выберите значение';
    }

    function closeCustomSelect() {
        if (!activeCustomSelect) return;
        activeCustomSelect.menu.classList.remove('is-open');
        activeCustomSelect.button.setAttribute('aria-expanded', 'false');
        activeCustomSelect = null;
    }

    function enhanceCustomSelect(select) {
        if (customSelectRegistry.has(select) || select.multiple || Number(select.size) > 1) return;
        const wrapper = document.createElement('span');
        wrapper.className = 'custom-select';
        if (select.classList.contains('person-filter')) wrapper.classList.add('custom-select--person-filter');
        if (select.classList.contains('compact-select')) wrapper.classList.add('custom-select--compact');
        select.before(wrapper);
        wrapper.appendChild(select);
        select.classList.add('native-select-proxy');
        select.tabIndex = -1;

        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'custom-select-trigger';
        button.setAttribute('aria-haspopup', 'listbox');
        button.setAttribute('aria-expanded', 'false');
        button.setAttribute('aria-label', selectLabel(select));
        button.innerHTML = '<span></span><i aria-hidden="true"></i>';
        wrapper.appendChild(button);

        const menu = document.createElement('div');
        menu.className = 'custom-select-menu';
        menu.id = `custom-select-${customSelectRegistry.size + 1}`;
        menu.setAttribute('role', 'listbox');
        button.setAttribute('aria-controls', menu.id);
        document.body.appendChild(menu);
        const control = { select, button, menu, activeIndex: select.selectedIndex };
        customSelectRegistry.set(select, control);

        const sync = () => {
            const selected = select.options[select.selectedIndex];
            button.querySelector('span').textContent = selected?.textContent || 'Выберите значение';
            button.disabled = select.disabled;
            button.classList.toggle('is-placeholder', !select.value);
            button.classList.toggle('is-invalid', select.required && !select.value);
            control.activeIndex = Math.max(0, select.selectedIndex);
        };

        const buildMenu = () => {
            menu.replaceChildren();
            [...select.options].forEach((option, index) => {
                const item = document.createElement('button');
                item.type = 'button';
                item.className = 'custom-select-option';
                item.setAttribute('role', 'option');
                item.setAttribute('aria-selected', String(index === select.selectedIndex));
                item.disabled = option.disabled;
                item.dataset.index = String(index);
                item.textContent = option.textContent;
                item.addEventListener('click', () => {
                    select.selectedIndex = index;
                    select.dispatchEvent(new Event('input', { bubbles: true }));
                    select.dispatchEvent(new Event('change', { bubbles: true }));
                    sync();
                    closeCustomSelect();
                    button.focus();
                });
                menu.appendChild(item);
            });
        };

        const highlight = index => {
            const options = [...select.options];
            if (!options.length) return;
            let next = Math.max(0, Math.min(index, options.length - 1));
            while (options[next]?.disabled && next !== control.activeIndex) next += next > control.activeIndex ? 1 : -1;
            if (!options[next] || options[next].disabled) return;
            control.activeIndex = next;
            $$('.custom-select-option', menu).forEach((item, itemIndex) => item.classList.toggle('is-active', itemIndex === next));
            const item = menu.children[next];
            if (item?.offsetTop < menu.scrollTop) menu.scrollTop = item.offsetTop;
            else if (item && item.offsetTop + item.offsetHeight > menu.scrollTop + menu.clientHeight) {
                menu.scrollTop = item.offsetTop + item.offsetHeight - menu.clientHeight;
            }
        };

        const open = () => {
            if (button.disabled) return;
            if (activeCustomSelect === control) { closeCustomSelect(); return; }
            closeCustomSelect();
            buildMenu();
            const rect = button.getBoundingClientRect();
            const viewportGutter = 8;
            const menuGap = 7;
            const menuWidth = Math.min(rect.width, window.innerWidth - viewportGutter * 2);
            const spaceBelow = window.innerHeight - rect.bottom - menuGap - viewportGutter;
            const spaceAbove = rect.top - menuGap - viewportGutter;
            const openAbove = spaceBelow < 220 && spaceAbove > spaceBelow;
            const availableSpace = openAbove ? spaceAbove : spaceBelow;
            menu.dataset.placement = openAbove ? 'above' : 'below';
            menu.style.left = `${Math.max(viewportGutter, Math.min(rect.left, window.innerWidth - menuWidth - viewportGutter))}px`;
            menu.style.width = `${menuWidth}px`;
            menu.style.maxHeight = `${Math.max(0, Math.min(360, availableSpace))}px`;
            menu.style.top = openAbove ? 'auto' : `${rect.bottom + menuGap}px`;
            menu.style.bottom = openAbove ? `${window.innerHeight - rect.top + menuGap}px` : 'auto';
            menu.classList.add('is-open');
            button.setAttribute('aria-expanded', 'true');
            activeCustomSelect = control;
            highlight(select.selectedIndex);
        };

        button.addEventListener('click', open);
        button.addEventListener('keydown', event => {
            if (event.key === 'Escape') { closeCustomSelect(); return; }
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                if (activeCustomSelect === control) {
                    menu.children[control.activeIndex]?.click();
                } else open();
                return;
            }
            if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
            event.preventDefault();
            if (activeCustomSelect !== control) open();
            if (event.key === 'Home') highlight(0);
            else if (event.key === 'End') highlight(select.options.length - 1);
            else highlight(control.activeIndex + (event.key === 'ArrowDown' ? 1 : -1));
        });
        select.addEventListener('change', sync);
        select.addEventListener('invalid', event => {
            event.preventDefault();
            button.classList.add('is-invalid');
            button.focus();
        });
        new MutationObserver(sync).observe(select, { childList: true, subtree: true, attributes: true });
        sync();
    }

    function setupCustomSelects(root = document) {
        $$('select:not([data-native-select])', root).forEach(enhanceCustomSelect);
    }

    document.addEventListener('pointerdown', event => {
        if (activeCustomSelect && !activeCustomSelect.button.contains(event.target) && !activeCustomSelect.menu.contains(event.target)) closeCustomSelect();
    });
    window.addEventListener('resize', closeCustomSelect);
    document.addEventListener('scroll', event => {
        if (!activeCustomSelect || activeCustomSelect.menu === event.target || activeCustomSelect.menu.contains(event.target)) return;
        closeCustomSelect();
    }, true);
    new MutationObserver(records => records.forEach(record => record.addedNodes.forEach(node => {
        if (node.nodeType === Node.ELEMENT_NODE) setupCustomSelects(node.matches?.('select') ? node.parentElement : node);
    }))).observe(document.documentElement, { childList: true, subtree: true });

    function setupTheme() {
        const media = window.matchMedia('(prefers-color-scheme: dark)');
        const storedTheme = () => {
            try {
                const value = localStorage.getItem(themeStorageKey);
                return value === 'light' || value === 'dark' ? value : null;
            } catch (error) {
                return null;
            }
        };
        const applyTheme = theme => {
            document.documentElement.dataset.theme = theme;
            document.documentElement.style.colorScheme = theme;
            document.querySelector('meta[name="theme-color"]')?.setAttribute(
                'content', theme === 'dark' ? '#20231f' : '#f5f1e8'
            );
            $$('[data-theme-toggle]').forEach(button => {
                const label = theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему';
                button.setAttribute('aria-label', label);
                button.setAttribute('title', label);
                button.setAttribute('aria-pressed', String(theme === 'dark'));
            });
        };

        applyTheme(storedTheme() || (media.matches ? 'dark' : 'light'));
        $$('[data-theme-toggle]').forEach(button => button.addEventListener('click', () => {
            const nextTheme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
            try { localStorage.setItem(themeStorageKey, nextTheme); } catch (error) { /* noop */ }
            applyTheme(nextTheme);
        }));
        media.addEventListener?.('change', event => {
            if (!storedTheme()) applyTheme(event.matches ? 'dark' : 'light');
        });
    }

    async function api(url, options = {}) {
        const config = { ...options, headers: { ...(options.headers || {}) } };
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes((config.method || 'GET').toUpperCase())) {
            config.headers['X-CSRF-Token'] = document.querySelector('meta[name="csrf-token"]')?.content || '';
        }
        if (config.body && typeof config.body !== 'string' && !(config.body instanceof FormData)) {
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
        const currency = state.bootstrap?.settings?.currency || '₽';
        return `${prefix}${new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(number)} ${currency}`;
    }

    function nativeMoney(value, code) {
        return `${new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(value || 0))} ${escapeHtml(code || '')}`;
    }

    function applyRuntimeSettings() {
        const currency = state.bootstrap?.settings?.currency || '₽';
        $$('[data-currency]').forEach(node => { node.textContent = currency; });
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
        node.setAttribute('role', type === 'error' ? 'alert' : 'status');
        node.textContent = message;
        $('#toastStack').appendChild(node);
        setTimeout(() => node.remove(), 3500);
    }

    function openModal(id) {
        const modal = document.getElementById(id);
        state.lastFocused = document.activeElement;
        modal?.classList.add('open');
        modal?.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');
        window.setTimeout(() => {
            const field = modal?.querySelector('input:not([type="hidden"]), select, textarea');
            (field || modal?.querySelector('button'))?.focus();
        }, 40);
    }

    function closeModals() {
        $$('.modal-backdrop').forEach(modal => {
            modal.classList.remove('open');
            modal.setAttribute('aria-hidden', 'true');
        });
        document.body.classList.remove('modal-open');
        state.lastFocused?.focus?.();
    }

    function personOptions(includeAll = false) {
        const head = includeAll ? '<option value="">Все вместе</option>' : '<option value="">Общее</option>';
        return head + state.bootstrap.people.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
    }

    function accountOptions(kind = null, includeCurrency = true) {
        return state.bootstrap.accounts
            .filter(a => (!kind || a.account_type === kind) && (includeCurrency || a.account_type !== 'currency'))
            .map(a => `<option value="${a.id}">${escapeHtml(a.name)} · ${a.account_type === 'currency' ? nativeMoney(a.balance, a.currency_code) : money(a.balance)}</option>`).join('');
    }

    function categoryOptions(type, includeAutomatic = false) {
        const automatic = includeAutomatic ? '<option value="">Определить автоматически</option>' : '';
        return automatic + state.bootstrap.categories
            .filter(c => c.type === type)
            .map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
    }

    function setupTransactionModal() {
        const form = $('#transactionForm');
        if (!form) return;
        form.tx_date.value = state.bootstrap.today;
        form.person_id.innerHTML = personOptions(false);
        form.account_id.innerHTML = accountOptions(null, false);
        form.target_account_id.innerHTML = accountOptions();
        const targetAmountField = $('#targetAmountField');
        const syncTargetAmount = () => {
            const target = state.bootstrap.accounts.find(account => account.id === Number(form.target_account_id.value));
            targetAmountField.classList.toggle('hidden', form.tx_type.value !== 'transfer' || target?.account_type !== 'currency');
            targetAmountField.firstChild.textContent = target?.account_type === 'currency'
                ? `Сумма зачисления, ${target.currency_code} ` : 'Сумма зачисления ';
        };

        const setType = type => {
            form.tx_type.value = type;
            $$('[data-tx-type]', form).forEach(btn => {
                const active = btn.dataset.txType === type;
                btn.classList.toggle('active', active);
                btn.setAttribute('aria-pressed', String(active));
            });
            const categoryField = $('#categoryField');
            const targetField = $('#targetAccountField');
            if (type === 'transfer') {
                categoryField.classList.add('hidden');
                targetField.classList.remove('hidden');
                form.category_id.required = false;
                form.target_account_id.required = true;
                form.account_id.innerHTML = accountOptions(null, false);
                form.target_account_id.innerHTML = accountOptions();
                syncTargetAmount();
            } else {
                categoryField.classList.remove('hidden');
                targetField.classList.add('hidden');
                form.category_id.required = false;
                form.target_account_id.required = false;
                form.category_id.innerHTML = categoryOptions(type, true);
                form.account_id.innerHTML = accountOptions(null, false);
                targetAmountField.classList.add('hidden');
                form.target_amount.value = '';
            }
        };

        form.target_account_id.addEventListener('change', syncTargetAmount);

        $$('[data-tx-type]', form).forEach(btn => btn.addEventListener('click', () => setType(btn.dataset.txType)));
        $$('[data-open-transaction]').forEach(btn => btn.addEventListener('click', () => {
            setType(btn.dataset.defaultType || 'expense');
            openModal('transactionModal');
        }));
        $$('[data-close-modal]').forEach(btn => btn.addEventListener('click', closeModals));
        $$('.modal-backdrop').forEach(modal => modal.addEventListener('click', event => {
            if (event.target === modal) closeModals();
        }));
        document.addEventListener('keydown', event => {
            const openBackdrop = $('.modal-backdrop.open');
            if (!openBackdrop) return;
            if (event.key === 'Escape') {
                closeModals();
                return;
            }
            if (event.key !== 'Tab') return;
            const focusable = $$('button:not(:disabled), input:not([type="hidden"]):not(:disabled), select:not(:disabled), textarea:not(:disabled), [href]', openBackdrop);
            if (!focusable.length) return;
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        });

        form.addEventListener('submit', async event => {
            event.preventDefault();
            const data = Object.fromEntries(new FormData(form).entries());
            const incomeAccount = state.bootstrap.accounts.find(account => account.id === Number(data.account_id));
            const shouldOfferAllocation = data.tx_type === 'income'
                && ['checking', 'cash'].includes(incomeAccount?.account_type);
            try {
                await api('/api/transactions', { method: 'POST', body: data });
                toast('Операция сохранена');
                closeModals();
                form.reset();
                form.tx_date.value = state.bootstrap.today;
                await refreshBootstrap();
                await loadCurrentPage();
                if (shouldOfferAllocation) {
                    const query = new URLSearchParams({ period: 'month', anchor: data.tx_date || state.bootstrap.today });
                    if (data.person_id) query.set('person_id', data.person_id);
                    const summary = await api(`/api/summary?${query}`);
                    openAllocationPrompt(summary.allocation_plan);
                }
            } catch (error) { toast(error.message, 'error'); }
        });
    }

    function setupNavigation() {
        const menuButton = $('#mobileMenu');
        const sidebar = $('#sidebar');
        const closeSidebar = () => {
            sidebar?.classList.remove('open');
            menuButton?.setAttribute('aria-expanded', 'false');
            menuButton?.setAttribute('aria-label', 'Открыть меню');
        };
        menuButton?.setAttribute('aria-expanded', 'false');
        menuButton?.addEventListener('click', () => {
            const isOpen = sidebar?.classList.toggle('open') || false;
            menuButton.setAttribute('aria-expanded', String(isOpen));
            menuButton.setAttribute('aria-label', isOpen ? 'Закрыть меню' : 'Открыть меню');
        });
        $('#sidebarBackdrop')?.addEventListener('click', closeSidebar);
        $$('.nav-item', sidebar).forEach(link => link.addEventListener('click', closeSidebar));
        $$('[data-period]').forEach(button => button.setAttribute('aria-pressed', String(button.classList.contains('active'))));
        $$('[data-period]').forEach(button => button.addEventListener('click', () => {
            state.period = button.dataset.period;
            state.txPage = 1;
            $$('[data-period]').forEach(b => {
                const active = b === button;
                b.classList.toggle('active', active);
                b.setAttribute('aria-pressed', String(active));
            });
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
        const names = { income: 'Доход', expense: 'Расход', transfer: 'Перевод', interest: 'Начисление процентов' };
        const icon = item.category_icon || ({ transfer: 'trend', interest: 'interest' }[item.tx_type] || 'category');
        const title = item.category_name || names[item.tx_type];
        const amountPrefix = item.tx_type === 'income' || item.tx_type === 'interest' ? '+' : item.tx_type === 'expense' ? '−' : '';
        return `<div class="transaction-row">
            <div class="tx-icon" style="color:${escapeHtml(item.category_color || '#8eb49b')}">${iconSvg(icon)}</div>
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
        const [data, tx, budgets] = await Promise.all([
            api(`/api/summary?${query}`),
            api(`/api/transactions?${query}&per_page=6`),
            api(`/api/budgets?anchor=${state.anchor}`),
        ]);
        setPeriodLabel(data);
        const current = data.current;
        $('#lifeBalance').textContent = money(data.life_balance);
        const savingsBalance = $('#savingsBalance');
        if (savingsBalance) savingsBalance.textContent = money(data.savings_balance);
        const currencyBalance = $('#currencyBalance');
        if (currencyBalance) currencyBalance.textContent = money(data.currency_balance);
        $('#investmentBalance').textContent = money(data.investment_balance);
        $('#totalCapital').textContent = money(data.total_capital);
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
        const allocation = data.allocation_plan;
        $('#allocationIncome').textContent = money(allocation.income);
        $('#allocationAdvice').textContent = allocation.advice;
        const allocationIcons = {
            spending: 'allocation-spending',
            savings: 'allocation-savings',
            currency: 'allocation-currency',
        };
        $('#allocationGrid').innerHTML = allocation.buckets.map(bucket => {
            const status = bucket.over > 0
                ? `выше плана на ${money(bucket.over)}`
                : bucket.key === 'spending' ? `ещё доступно ${money(bucket.remaining)}` : `осталось направить ${money(bucket.remaining)}`;
            const destination = bucket.key === 'spending'
                ? `потрачено ${money(bucket.actual)}`
                : bucket.destination ? `счёт «${escapeHtml(bucket.destination)}» · уже ${money(bucket.actual)}` : `создайте подходящий счёт · уже ${money(bucket.actual)}`;
            return `<div class="allocation-bucket ${bucket.key} ${bucket.over > 0 ? 'is-over' : ''}">
                <div class="allocation-bucket-head"><span class="allocation-icon">${iconSvg(allocationIcons[bucket.key])}</span><span>${escapeHtml(bucket.label)}</span></div>
                <strong>${money(bucket.planned)}</strong>
                <div class="progress-track"><i style="width:${bucket.progress}%"></i></div>
                <div class="allocation-bucket-meta"><span>${destination}</span><b>${status}</b></div>
            </div>`;
        }).join('');
        const spending = data.spending_stats;
        $('#averageDailyExpense').textContent = money(spending.average_per_day);
        $('#averageExpense').textContent = money(spending.average_transaction);
        $('#expenseCount').textContent = new Intl.NumberFormat('ru-RU').format(spending.transaction_count);
        $('#activeExpenseDays').textContent = `${spending.active_days} ${pluralize(spending.active_days, ['активный день', 'активных дня', 'активных дней'])}`;
        $('#largestExpense').textContent = spending.largest ? money(spending.largest.amount) : '—';
        $('#largestExpenseMeta').textContent = spending.largest
            ? `${spending.largest.category_name} · ${formatDate(spending.largest.tx_date)}`
            : 'Расходов пока нет';
        drawLineChart($('#trendChart'), data.trend);
        renderCategories(data.breakdown);
        renderBudgets(budgets, $('#budgetOverview'));
        $('#recentTransactions').innerHTML = tx.items.length ? tx.items.map(transactionRow).join('') : '<div class="empty-state">Операций за период нет</div>';
    }

    function pluralize(value, forms) {
        const number = Math.abs(Number(value)) % 100;
        const last = number % 10;
        if (number > 10 && number < 20) return forms[2];
        if (last > 1 && last < 5) return forms[1];
        if (last === 1) return forms[0];
        return forms[2];
    }

    function renderCategories(items) {
        const container = $('#categoryBreakdown');
        if (!container) return;
        if (!items.length) { container.innerHTML = '<div class="empty-state">Расходов пока нет</div>'; return; }
        const total = items.reduce((sum, item) => sum + Number(item.amount), 0);
        container.innerHTML = items.map(item => {
            const pct = total ? Number(item.amount) / total * 100 : 0;
            return `<div class="category-row" style="--cat-color:${escapeHtml(item.color)}">
                <div class="category-icon">${iconSvg(item.icon)}</div>
                <div><div class="category-name"><span>${escapeHtml(item.name)}</span><span>${pct.toFixed(0)}%</span></div><div class="progress-track"><i style="width:${pct}%"></i></div><div class="category-profile-meta">${item.transaction_count} ${pluralize(item.transaction_count, ['операция', 'операции', 'операций'])} · средний чек ${money(item.average_transaction)}</div></div>
                <strong>${money(item.amount)}</strong>
            </div>`;
        }).join('');
    }

    function renderBudgets(items, container) {
        if (!container) return;
        if (!items.length) { container.innerHTML = '<div class="empty-state">Добавьте лимиты в настройках</div>'; return; }
        container.innerHTML = items.slice(0, 5).map(item => `<div class="category-row"><div class="category-icon">${iconSvg(item.icon)}</div><div><div class="category-name"><span>${escapeHtml(item.name)}</span><span>${money(item.spent)} / ${money(item.monthly_limit)}</span></div><div class="progress-track"><i style="width:${Math.min(100, item.progress)}%;background:${item.status === 'over' ? 'var(--red)' : item.status === 'warning' ? 'var(--yellow)' : 'var(--green)'}"></i></div></div><strong>${item.progress.toFixed(0)}%</strong></div>`).join('');
    }

    async function loadTransactions() {
        const query = new URLSearchParams({ period: state.period, anchor: state.anchor, page: state.txPage, per_page: 20 });
        if (state.personId) query.set('person_id', state.personId);
        const type = $('#txTypeFilter')?.value;
        if (type) query.set('type', type);
        const search = $('#txSearch')?.value.trim();
        if (search) query.set('q', search);
        const exportLink = $('#exportTransactions');
        if (exportLink) exportLink.href = `/api/transactions/export.csv?period=${state.period}&anchor=${state.anchor}`;
        const [summary, data] = await Promise.all([api(`/api/summary?${query}`), api(`/api/transactions?${query}`)]);
        setPeriodLabel(summary);
        const tbody = $('#transactionsTable');
        tbody.innerHTML = data.items.length ? data.items.map(item => {
            const names = { income: 'Доход', expense: 'Расход', transfer: 'Перевод', interest: 'Проценты' };
            const prefix = ['income', 'interest'].includes(item.tx_type) ? '+' : item.tx_type === 'expense' ? '−' : '';
            const categoryIcon = item.category_icon || (item.tx_type === 'interest' ? 'interest' : item.tx_type === 'transfer' ? 'trend' : 'category');
            const categoryName = item.category_name || (item.tx_type === 'transfer' ? 'Между счетами' : item.tx_type === 'interest' ? 'Начисление' : 'Без категории');
            return `<tr>
                <td data-label="Дата">${formatDate(item.tx_date, { day: '2-digit', month: '2-digit', year: 'numeric' })}</td>
                <td data-label="Операция"><div class="table-main"><div class="tx-icon">${iconSvg(categoryIcon)}</div><div><strong>${escapeHtml(categoryName)}</strong><div class="subtext">${names[item.tx_type]}</div></div></div></td>
                <td data-label="Заметка"><span>${escapeHtml(item.note || 'Без пометки')}</span></td>
                <td data-label="Человек">${item.person_name ? `<span class="person-pill" style="--avatar:${escapeHtml(item.avatar_color)}"><i>${escapeHtml(item.person_name[0])}</i>${escapeHtml(item.person_name)}</span>` : '—'}</td>
                <td data-label="Счёт">${escapeHtml(item.account_name || '—')}${item.target_account_name ? `<div class="subtext">Счёт назначения: ${escapeHtml(item.target_account_name)}</div>` : ''}</td>
                <td data-label="Сумма" class="align-right"><strong class="tx-amount ${item.tx_type}">${prefix}${money(item.amount)}</strong></td>
                <td class="row-actions">${item.tx_type !== 'interest' ? `<button class="delete-btn" data-edit-tx="${item.id}" data-date="${item.tx_date}" data-note="${escapeHtml(item.note || '')}" title="Исправить заметку или дату" aria-label="Исправить операцию">${iconSvg('edit')}</button><button class="delete-btn" data-duplicate-tx="${item.id}" title="Дублировать" aria-label="Дублировать операцию">${iconSvg('copy')}</button><button class="delete-btn" data-delete-tx="${item.id}" title="Удалить" aria-label="Удалить операцию">${iconSvg('trash')}</button>` : ''}</td>
            </tr>`;
        }).join('') : '<tr><td colspan="7"><div class="empty-state">За этот период операций нет</div></td></tr>';
        $$('[data-delete-tx]').forEach(btn => btn.addEventListener('click', () => deleteTransaction(btn.dataset.deleteTx)));
        $$('[data-duplicate-tx]').forEach(btn => btn.addEventListener('click', () => duplicateTransaction(btn.dataset.duplicateTx)));
        $$('[data-edit-tx]').forEach(btn => btn.addEventListener('click', () => editTransaction(btn.dataset.editTx, btn.dataset.date, btn.dataset.note)));
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

    async function duplicateTransaction(id) {
        try { await api(`/api/transactions/${id}/duplicate`, { method: 'POST' }); toast('Операция продублирована на сегодня'); await refreshBootstrap(); loadTransactions(); }
        catch (error) { toast(error.message, 'error'); }
    }

    function editTransaction(id, txDate, note) {
        openEntityForm('Исправить операцию', `<label>Дата<input name="tx_date" type="date" value="${escapeHtml(txDate)}" required></label><label>Заметка<textarea name="note">${escapeHtml(note)}</textarea></label>`, async data => { try { await api(`/api/transactions/${id}`, { method: 'PATCH', body: data }); toast('Операция обновлена'); closeModals(); loadTransactions(); } catch (error) { toast(error.message, 'error'); } });
    }

    function layoutEntityFormFields(container) {
        const fields = $$('.entity-form__fields > label', container);
        fields.forEach(field => {
            field.classList.add('entity-form__field');
            field.classList.toggle('entity-form__field--wide', Boolean(field.querySelector('textarea')));
            field.classList.remove('entity-form__field--auto-wide');
        });
        const regularFields = fields.filter(field =>
            !field.classList.contains('hidden') && !field.querySelector('textarea')
        );
        if (regularFields.length % 2) {
            regularFields.at(-1).classList.add('entity-form__field--auto-wide');
        }
    }

    function openEntityForm(title, body, onSubmit) {
        const container = $('#entityModalContent');
        container.setAttribute('aria-labelledby', 'entityModalTitle');
        container.classList.add('entity-modal-card');
        container.innerHTML = `<div class="modal-head entity-modal__header"><div><div class="eyebrow">Детали</div><h2 id="entityModalTitle">${escapeHtml(title)}</h2></div><button class="icon-btn" type="button" data-close-entity aria-label="Закрыть окно">${iconSvg('close')}</button></div><form id="entityForm" class="entity-form"><div class="entity-form__body"><div class="entity-form__fields">${body}</div></div><div class="modal-actions entity-form__actions"><button type="button" class="btn btn-ghost" data-close-entity>Отмена</button><button type="submit" class="btn btn-primary">Сохранить</button></div></form>`;
        layoutEntityFormFields(container);
        $$('[data-close-entity]', container).forEach(btn => btn.addEventListener('click', closeModals));
        $('#entityForm', container).addEventListener('submit', async event => {
            event.preventDefault();
            await onSubmit(Object.fromEntries(new FormData(event.target).entries()));
        });
        openModal('entityModal');
    }

    function openAllocationPrompt(plan) {
        const container = $('#entityModalContent');
        const actionLabels = {
            spending: `Оставить на счёте «${escapeHtml(plan.source_account || 'на жизнь')}»`,
            savings: 'Перевести в накопления / инвестиции',
            currency: 'Направить в валютный резерв',
        };
        container.classList.add('entity-modal-card');
        container.setAttribute('aria-labelledby', 'allocationPromptTitle');
        container.innerHTML = `<div class="modal-head entity-modal__header"><div><div class="eyebrow">Доход получен</div><h2 id="allocationPromptTitle">Распределение на этот месяц</h2></div><button class="icon-btn" type="button" data-close-allocation aria-label="Закрыть окно">${iconSvg('close')}</button></div>
            <div class="allocation-prompt">
                <p>Общий доход за месяц: <strong>${money(plan.income)}</strong>. Вот что стоит сделать с учётом уже проведённых операций.</p>
                <div class="allocation-prompt-list">${plan.buckets.map(bucket => `<div><span>${actionLabels[bucket.key]}</span><strong>${money(bucket.remaining)}</strong><small>план ${money(bucket.planned)} · уже ${money(bucket.actual)}</small></div>`).join('')}</div>
                <div class="allocation-advice">${iconSvg('target')}<p>${escapeHtml(plan.advice)}</p></div>
            </div>
            <div class="modal-actions entity-form__actions"><a class="btn btn-ghost" href="/settings">Изменить правила</a><button class="btn btn-primary" type="button" data-close-allocation>Понятно</button></div>`;
        $$('[data-close-allocation]', container).forEach(button => button.addEventListener('click', closeModals));
        openModal('entityModal');
    }

    function openCategoryForm() {
        openEntityForm('Новая категория', `
            <label>Название<input name="name" required placeholder="Например: питомцы"></label>
            <label>Тип<select name="type"><option value="expense">Расход</option><option value="income">Доход</option></select></label>
            <label>Цвет<input name="color" type="color" value="#7c5cff"></label>`, async data => {
            try {
                await api('/api/categories', { method: 'POST', body: data });
                toast('Категория добавлена'); closeModals(); await refreshBootstrap(); await loadCurrentPage();
            } catch (error) { toast(error.message, 'error'); }
        });
    }

    async function loadInvestments() {
        const [accounts, tx] = await Promise.all([
            api('/api/accounts'),
            api('/api/transactions?period=month&anchor=' + state.anchor + '&per_page=20'),
        ]);
        const investments = accounts.filter(a => ['savings', 'deposit', 'investment'].includes(a.account_type) && a.is_active);
        const typeLabels = { savings: 'Накопительный', deposit: 'Вклад', investment: 'Инвестиционный' };
        $('#investmentAccounts').innerHTML = investments.length ? investments.map(account => `<article class="card account-card"><div class="card-kicker">${typeLabels[account.account_type] || 'Счёт'}</div><h3>${escapeHtml(account.name)}</h3><strong>${money(account.balance)}</strong><div class="account-meta"><span>${Number(account.annual_rate).toFixed(2)}% годовых</span><span>${account.interest_enabled ? `выплата раз в месяц · проведено по ${formatDate(account.last_accrual_date)}` : 'автоначисление выключено'}</span></div><button class="btn btn-ghost" type="button" data-configure-interest="${account.id}">${iconSvg('edit')}Настроить ставку</button></article>`).join('') : '<div class="card empty-state">Добавьте накопительный или инвестиционный счёт в настройках</div>';
        $('#investmentTransactions').innerHTML = tx.items.filter(item => ['transfer', 'interest'].includes(item.tx_type)).map(transactionRow).join('') || '<div class="empty-state">Пополнений пока нет</div>';
        $$('[data-configure-interest]').forEach(button => button.addEventListener('click', () => {
            openAccountForm(accounts.find(account => account.id === Number(button.dataset.configureInterest)));
        }));
        setupInvestmentCalculator(investments.find(a => a.account_type === 'investment') || investments[0]);
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
        const priorityLabels = { high: 'Высокий', medium: 'Средний', low: 'Низкий' };
        $('#purchaseGrid').innerHTML = data.items.length ? data.items.map(item => `<article class="card entity-card">
            <div class="entity-top"><div class="entity-title"><div class="card-kicker">Планируемая покупка · ${escapeHtml(item.person_name || 'Общая')}</div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.note || 'Без заметки')}</p></div><span class="priority ${item.priority}">${priorityLabels[item.priority] || escapeHtml(item.priority)}</span></div>
            <div class="entity-amount">${money(item.cost)}</div>
            <div class="entity-progress"><div class="meta"><span>Накоплено ${money(item.saved_amount)}</span><span>${item.progress}%</span></div><div class="progress-track"><i style="width:${item.progress}%;background:var(--green)"></i></div></div>
            <div class="entity-stats"><div><span>В день</span><strong>${money(item.daily_save)}</strong></div><div><span>В неделю</span><strong>${money(item.weekly_save)}</strong></div><div><span>В месяц</span><strong>${money(item.monthly_save)}</strong></div><div><span>До срока</span><strong>${item.days_left} дн.</strong></div></div>
            <div class="affordability ${item.affordability}">${labels[item.affordability]}</div>
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
        const priorityLabels = { high: 'Высокий', medium: 'Средний', low: 'Низкий' };
        $('#goalsGrid').innerHTML = data.length ? data.map(item => `<article class="card entity-card">
            <div class="entity-top"><div class="entity-title"><div class="card-kicker">Накопительная цель · ${escapeHtml(item.person_name || 'Общая')}</div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.note || 'Без заметки')}${item.account_name ? ` · счёт «${escapeHtml(item.account_name)}»` : ''}</p></div><span class="priority ${item.priority}">${priorityLabels[item.priority] || escapeHtml(item.priority)}</span></div>
            <div class="entity-amount">${money(item.target_amount)}</div>
            <div class="entity-progress"><div class="meta"><span>Достигнуто ${money(item.current_amount)}</span><span>${item.progress}%</span></div><div class="progress-track"><i style="width:${item.progress}%;background:var(--primary)"></i></div></div>
            <div class="entity-stats"><div><span>Осталось</span><strong>${money(item.remaining)}</strong></div><div><span>Нужно в месяц</span><strong>${money(item.monthly_needed)}</strong></div><div><span>Срок</span><strong>${formatDate(item.target_date)}</strong></div><div><span>До цели</span><strong>${item.days_left} дн.</strong></div></div>
            <div class="entity-footer">${item.account_id ? '<span class="muted">Прогресс равен балансу связанного счёта</span>' : `<button class="btn btn-secondary" data-fund-goal="${item.id}" data-current="${item.current_amount}">Добавить прогресс</button>`}<button class="btn btn-ghost" data-delete-goal="${item.id}">Удалить</button></div>
        </article>`).join('') : '<div class="card empty-state">Создайте первую финансовую цель</div>';
        $$('[data-fund-goal]').forEach(btn => btn.addEventListener('click', () => fundEntity('goals', btn.dataset.fundGoal, Number(btn.dataset.current), loadGoals, 'current_amount')));
        $$('[data-delete-goal]').forEach(btn => btn.addEventListener('click', () => deleteEntity('goals', btn.dataset.deleteGoal, loadGoals)));
    }

    function openGoalForm() {
        const goalAccounts = state.bootstrap.accounts.filter(account => ['savings', 'deposit', 'currency', 'investment'].includes(account.account_type));
        openEntityForm('Новая цель', `
            <label>Название<input name="title" required placeholder="Например: финансовая подушка"></label>
            <label>Целевая сумма<input name="target_amount" type="number" min="1" required></label>
            <label>Уже накоплено<input name="current_amount" type="number" min="0" value="0"></label>
            <label>Срок<input name="target_date" type="date"></label>
            <label>Чья цель<select name="person_id">${personOptions(false)}</select></label>
            <label>Связанный счёт<select name="account_id"><option value="">Без связи</option>${goalAccounts.map(account => `<option value="${account.id}">${escapeHtml(account.name)}</option>`).join('')}</select></label>
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
        $('#peopleMetrics').innerHTML = data.length ? data.map(item => {
            const p = item.person, m = item.current;
            return `<article class="card person-card" style="--avatar:${escapeHtml(p.avatar_color)}">
                <div class="person-head"><div class="big-avatar">${escapeHtml(p.name[0])}</div><div><h3>${escapeHtml(p.name)}</h3><span>Персональная статистика за период</span></div></div>
                <div class="person-metrics"><div><span>Доход</span><strong class="tx-amount income">${money(m.income)}</strong></div><div><span>Расход</span><strong class="tx-amount expense">${money(m.expense)}</strong></div><div><span>Инвестиции</span><strong class="tx-amount transfer">${money(m.invested)}</strong></div></div>
                <div class="mini-score"><div><div class="card-kicker">Индекс действий</div><strong>${item.score.value}/100</strong></div><span class="priority ${item.score.tone === 'good' ? 'low' : item.score.tone === 'bad' ? 'high' : 'medium'}">${escapeHtml(item.score.label)}</span></div>
                <div class="person-categories"><div class="card-kicker">Главные категории расходов</div>${item.breakdown.slice(0,4).map(cat => `<div class="category-name"><span class="category-label">${iconSvg(cat.icon)}${escapeHtml(cat.name)}</span><strong>${money(cat.amount)}</strong></div>`).join('') || '<div class="muted">Нет расходов</div>'}</div>
            </article>`;
        }).join('') : '<div class="card empty-state">Персональная статистика появится после первых операций</div>';
    }

    const accountTypeLabels = {
        checking: 'Основной',
        cash: 'Наличные',
        savings: 'Накопительный',
        deposit: 'Вклад',
        currency: 'Валютный',
        investment: 'Инвестиционный',
    };
    const accountTypeIcons = {
        checking: 'account-checking',
        cash: 'account-cash',
        savings: 'account-savings',
        deposit: 'account-deposit',
        currency: 'account-currency',
        investment: 'account-investment',
    };

    function accountTypeOptions(selected = 'checking') {
        return Object.entries(accountTypeLabels)
            .map(([value, label]) => `<option value="${value}" ${value === selected ? 'selected' : ''}>${label}</option>`)
            .join('');
    }

    function openAccountForm(account = null) {
        const editing = Boolean(account);
        openEntityForm(editing ? 'Настроить счёт' : 'Новый счёт', `
            <label>Название<input name="name" value="${escapeHtml(account?.name || '')}" required placeholder="Например: Подушка безопасности"></label>
            <label>Тип счёта<select name="account_type">${accountTypeOptions(account?.account_type)}</select></label>
            <label>Годовая ставка, %<input name="annual_rate" type="number" min="0" max="100" step="0.01" value="${Number(account?.annual_rate || 0)}"><small>Используется для накопительных счетов, вкладов и инвестиций.</small></label>
            <label class="toggle-field"><input type="hidden" name="interest_enabled" value="false"><input name="interest_enabled" type="checkbox" value="true" ${account?.interest_enabled ? 'checked' : ''}><span><strong>Автоначисление процентов</strong><small>Считается по ежедневному остатку, проводится одной операцией после окончания месяца.</small></span></label>
            <label>Код валюты<input name="currency_code" maxlength="3" value="${escapeHtml(account?.currency_code || state.bootstrap.settings.base_currency_code || 'RUB')}" placeholder="USD"><small>Для валютного счёта.</small></label>
            <label>Курс к основной валюте<input name="exchange_rate" type="number" min="0.000001" step="0.000001" value="${Number(account?.exchange_rate || 1)}"><small>Сколько основной валюты стоит одна единица валюты счёта.</small></label>`, async data => {
            try {
                await api(editing ? `/api/accounts/${account.id}` : '/api/accounts', { method: editing ? 'PATCH' : 'POST', body: data });
                toast(editing ? 'Счёт обновлён' : 'Счёт добавлен');
                closeModals();
                await refreshBootstrap();
                await loadCurrentPage();
            } catch (error) { toast(error.message, 'error'); }
        });
    }

    async function loadSettings() {
        const [data, budgets, accounts] = await Promise.all([
            api('/api/settings'),
            api('/api/budgets'),
            api('/api/accounts'),
        ]);
        const form = $('#settingsForm');
        Object.entries(data).forEach(([key, value]) => { if (form.elements[key]) form.elements[key].value = value; });
        if (!form.dataset.ready) {
            form.dataset.ready = '1';
            form.addEventListener('submit', async event => {
                event.preventDefault();
                try {
                    await api('/api/settings', { method: 'PUT', body: Object.fromEntries(new FormData(form).entries()) });
                    await refreshBootstrap();
                    toast('Настройки сохранены и применены ко всем разделам');
                    await loadCurrentPage();
                }
                catch (error) { toast(error.message, 'error'); }
            });
        }
        const budgetCard = $('#budgetSettings');
        if (budgetCard) {
            budgetCard.innerHTML = budgets.length ? budgets.map(item => `<div class="category-row"><span class="category-label">${iconSvg(item.icon)}${escapeHtml(item.name)}</span><strong>${money(item.monthly_limit)}</strong><button class="delete-btn" data-remove-budget="${item.category_id}" aria-label="Удалить лимит ${escapeHtml(item.name)}">${iconSvg('trash')}</button></div>`).join('') : '<div class="empty-state">Лимитов пока нет</div>';
            $$('[data-remove-budget]', budgetCard).forEach(btn => btn.addEventListener('click', async () => { await api(`/api/budgets/${btn.dataset.removeBudget}`, { method: 'DELETE' }); loadSettings(); }));
        }
        const addBudgetButton = $('#addBudgetBtn');
        if (addBudgetButton && !addBudgetButton.dataset.ready) {
            addBudgetButton.dataset.ready = '1';
            addBudgetButton.addEventListener('click', () => openEntityForm('Лимит категории', `<label>Категория<select name="category_id">${categoryOptions('expense')}</select></label><label>Лимит в месяц<input name="monthly_limit" type="number" min="1" required></label>`, async data => { await api(`/api/budgets/${data.category_id}`, { method: 'PUT', body: data }); closeModals(); loadSettings(); }));
        }
        const categoryButton = $('#addSettingsCategory');
        if (categoryButton && !categoryButton.dataset.ready) {
            categoryButton.dataset.ready = '1';
            categoryButton.addEventListener('click', openCategoryForm);
        }
        const accountList = $('#accountSettings');
        if (accountList) {
            accountList.innerHTML = accounts.length ? accounts.map(account => `<article class="account-setting-row ${account.is_active ? '' : 'is-inactive'}">
                <div class="account-setting-icon">${iconSvg(accountTypeIcons[account.account_type] || 'account-checking')}</div>
                <div class="account-setting-main"><div><strong>${escapeHtml(account.name)}</strong><span>${accountTypeLabels[account.account_type] || 'Счёт'}${account.is_active ? '' : ' · отключён'}</span></div><b>${account.account_type === 'currency' ? `${nativeMoney(account.balance, account.currency_code)} · ${money(account.base_equivalent)}` : money(account.balance)}</b></div>
                <div class="account-setting-meta"><span>${account.account_type === 'currency' ? `курс ${Number(account.exchange_rate).toFixed(4)}` : `${Number(account.annual_rate).toFixed(2)}% годовых`}</span></div>
                <div class="account-setting-actions"><button class="btn btn-ghost" data-edit-account="${account.id}">${iconSvg('edit')}Настроить</button><button class="btn btn-ghost" data-toggle-account="${account.id}" data-active="${account.is_active}">${account.is_active ? 'Отключить' : 'Включить'}</button><button class="delete-btn" data-delete-account="${account.id}" aria-label="Удалить счёт ${escapeHtml(account.name)}">${iconSvg('trash')}</button></div>
            </article>`).join('') : '<div class="empty-state">Добавьте первый счёт</div>';
            $$('[data-edit-account]', accountList).forEach(button => button.addEventListener('click', () => openAccountForm(accounts.find(account => account.id === Number(button.dataset.editAccount)))));
            $$('[data-toggle-account]', accountList).forEach(button => button.addEventListener('click', async () => {
                try {
                    await api(`/api/accounts/${button.dataset.toggleAccount}`, { method: 'PATCH', body: { is_active: button.dataset.active !== '1' } });
                    await refreshBootstrap();
                    loadSettings();
                } catch (error) { toast(error.message, 'error'); }
            }));
            $$('[data-delete-account]', accountList).forEach(button => button.addEventListener('click', async () => {
                if (!confirm('Удалить счёт без возможности восстановления?')) return;
                try {
                    await api(`/api/accounts/${button.dataset.deleteAccount}`, { method: 'DELETE' });
                    toast('Счёт удалён');
                    await refreshBootstrap();
                    loadSettings();
                } catch (error) { toast(error.message, 'error'); }
            }));
        }
        const addAccountButton = $('#addAccountBtn');
        if (addAccountButton && !addAccountButton.dataset.ready) {
            addAccountButton.dataset.ready = '1';
            addAccountButton.addEventListener('click', () => openAccountForm());
        }
    }

    async function loadRecurring() {
        const items = await api('/api/recurring-transactions');
        const container = $('#recurringList');
        if (!container) return;
        const typeLabels = { expense: 'Расход', income: 'Доход', transfer: 'Перевод' };
        container.innerHTML = items.length ? items.map(item => `<article class="card entity-card"><div class="card-kicker">${escapeHtml(item.frequency === 'monthly' ? 'Ежемесячно' : 'Еженедельно')} · ${typeLabels[item.tx_type] || escapeHtml(item.tx_type)}</div><h3>${escapeHtml(item.title)}</h3><div class="entity-amount">${money(item.amount)}</div><p class="muted">Следующая дата: ${formatDate(item.next_date)} · ${escapeHtml(item.category_name || item.account_name)}</p><div class="entity-footer"><button class="btn btn-secondary" data-apply-recurring="${item.id}" ${item.is_active ? '' : 'disabled'}>Провести</button><button class="btn btn-ghost" data-toggle-recurring="${item.id}" data-active="${item.is_active}">${item.is_active ? 'Пауза' : 'Включить'}</button><button class="btn btn-danger" data-delete-recurring="${item.id}">${iconSvg('trash')}Удалить</button></div></article>`).join('') : '<div class="empty-state">Добавьте зарплату, аренду или подписку</div>';
        $$('[data-apply-recurring]').forEach(btn => btn.addEventListener('click', async () => { try { await api(`/api/recurring-transactions/${btn.dataset.applyRecurring}/apply`, { method: 'POST' }); toast('Операция проведена'); await refreshBootstrap(); loadRecurring(); } catch (error) { toast(error.message, 'error'); } }));
        $$('[data-toggle-recurring]').forEach(btn => btn.addEventListener('click', async () => { await api(`/api/recurring-transactions/${btn.dataset.toggleRecurring}`, { method: 'PATCH', body: { is_active: btn.dataset.active !== '1' } }); loadRecurring(); }));
        $$('[data-delete-recurring]').forEach(btn => btn.addEventListener('click', async () => {
            if (!confirm('Удалить регулярную операцию? Уже проведённые операции останутся в истории.')) return;
            try {
                await api(`/api/recurring-transactions/${btn.dataset.deleteRecurring}`, { method: 'DELETE' });
                toast('Регулярная операция удалена');
                await loadRecurring();
            } catch (error) { toast(error.message, 'error'); }
        }));
    }

    function openRecurringForm() {
        openEntityForm('Регулярная операция', `
            <label>Название<input name="title" required placeholder="Например: зарплата или аренда"></label>
            <label>Тип<select name="tx_type" id="recurringType"><option value="expense">Расход</option><option value="income">Доход</option><option value="transfer">Перевод между счетами</option></select></label>
            <label>Сумма<input name="amount" type="number" min="0.01" step="0.01" required></label>
            <label>Повтор<select name="frequency"><option value="monthly">Ежемесячно</option><option value="weekly">Еженедельно</option></select></label>
            <label>Первая дата<input name="next_date" type="date" value="${state.bootstrap.today}" required></label>
            <label id="recurringCategoryField">Категория<select name="category_id" required>${categoryOptions('expense')}</select></label>
            <label>Кто<select name="person_id">${personOptions(false)}</select></label>
            <label>Счёт<select name="account_id">${accountOptions(null, false)}</select></label>
            <label id="recurringTargetField" class="hidden">Счёт назначения<select name="target_account_id">${accountOptions()}</select></label>
            <label>Заметка<textarea name="note"></textarea></label>`, async data => {
            try {
                await api('/api/recurring-transactions', { method: 'POST', body: data });
                toast('Регулярная операция добавлена');
                closeModals();
                loadRecurring();
            } catch (error) { toast(error.message, 'error'); }
        });
        const form = $('#entityForm');
        const typeSelect = $('#recurringType', form);
        const categoryField = $('#recurringCategoryField', form);
        const targetField = $('#recurringTargetField', form);
        const syncFields = () => {
            const type = typeSelect.value;
            const isTransfer = type === 'transfer';
            categoryField.classList.toggle('hidden', isTransfer);
            targetField.classList.toggle('hidden', !isTransfer);
            categoryField.querySelector('select').disabled = isTransfer;
            categoryField.querySelector('select').required = !isTransfer;
            targetField.querySelector('select').disabled = !isTransfer;
            targetField.querySelector('select').required = isTransfer;
            if (!isTransfer) categoryField.querySelector('select').innerHTML = categoryOptions(type);
            layoutEntityFormFields(form);
        };
        typeSelect.addEventListener('change', syncFields);
        syncFields();
    }

    async function loadAutomation() {
        const [rules, plan] = await Promise.all([api('/api/category-rules'), api('/api/salary-plan')]);
        const form = $('#importForm');
        if (form && !form.dataset.ready) {
            form.dataset.ready = '1';
            form.account_id.innerHTML = accountOptions(null, false);
            form.person_id.innerHTML = personOptions(false);
            form.addEventListener('submit', async event => {
                event.preventDefault();
                try {
                    const data = await api('/api/imports/preview', { method: 'POST', body: new FormData(form) });
                    const errors = data.errors.map(item => `<div class="list-row is-warning"><span>Строка ${item.row_number}</span><strong>${escapeHtml(item.error)}</strong></div>`).join('');
                    $('#importPreview').innerHTML = `<p class="muted">Корректно: ${data.valid_rows} из ${data.total_rows}${data.preview_limited ? ' · показаны первые 100' : ''}</p>` + data.items.map(item => `<div class="list-row ${item.duplicate ? 'is-muted' : ''}"><span>${formatDate(item.tx_date)} · ${escapeHtml(item.note || 'Без описания')}</span><strong>${item.tx_type === 'expense' ? '−' : '+'}${money(item.amount)}${item.duplicate ? ' · дубль' : ''}</strong></div>`).join('') + errors;
                    $('#confirmImport').disabled = false;
                } catch (error) { toast(error.message, 'error'); }
            });
            $('#confirmImport').addEventListener('click', async () => {
                if (!confirm('Импортировать показанные корректные операции?')) return;
                try {
                    const result = await api('/api/imports/confirm', { method: 'POST', body: new FormData(form) });
                    toast(`Импортировано: ${result.imported}, пропущено: ${result.skipped}`);
                    $('#confirmImport').disabled = true;
                    await refreshBootstrap();
                    await loadAutomation();
                } catch (error) { toast(error.message, 'error'); }
            });
        }
        const labels = { spending: 'Оставить на жизнь', savings: 'Перевести в накопления', currency: 'Перевести в валютный резерв' };
        $('#salaryChecklist').innerHTML = plan.buckets.map(bucket => `<div class="list-row"><span>${labels[bucket.key]}</span><strong>${money(bucket.remaining)}</strong></div>`).join('') + `<p class="muted">${escapeHtml(plan.advice)}</p>`;
        const applyButton = $('#applySalaryPlan');
        if (applyButton && !applyButton.dataset.ready) {
            applyButton.dataset.ready = '1';
            applyButton.addEventListener('click', async () => {
                if (!confirm('Создать только недостающие переводы зарплатного плана?')) return;
                try {
                    const result = await api('/api/salary-plan/apply', { method: 'POST', body: { confirm: true } });
                    toast(`Создано переводов: ${result.created.length}`);
                    await refreshBootstrap();
                    loadAutomation();
                } catch (error) { toast(error.message, 'error'); }
            });
        }
        const ruleForm = $('#categoryRuleForm');
        if (ruleForm) {
            ruleForm.category_id.innerHTML = state.bootstrap.categories.map(category => `<option value="${category.id}">${escapeHtml(category.name)} · ${category.type === 'expense' ? 'расход' : 'доход'}</option>`).join('');
            if (!ruleForm.dataset.ready) {
                ruleForm.dataset.ready = '1';
                ruleForm.addEventListener('submit', async event => {
                    event.preventDefault();
                    try { await api('/api/category-rules', { method: 'POST', body: Object.fromEntries(new FormData(ruleForm).entries()) }); ruleForm.reset(); toast('Правило добавлено'); loadAutomation(); }
                    catch (error) { toast(error.message, 'error'); }
                });
            }
        }
        $('#categoryRules').innerHTML = rules.length ? rules.map(rule => `<div class="list-row ${rule.is_active ? '' : 'is-muted'}"><span>«${escapeHtml(rule.pattern)}» → ${escapeHtml(rule.category_name)} <small>приоритет ${rule.priority}</small></span><span class="row-buttons"><button class="btn btn-ghost" data-edit-rule="${rule.id}">${iconSvg('edit')}Изменить</button><button class="btn btn-ghost" data-toggle-rule="${rule.id}" data-active="${rule.is_active}">${rule.is_active ? 'Пауза' : 'Включить'}</button><button class="btn btn-danger" data-delete-rule="${rule.id}">${iconSvg('trash')}Удалить</button></span></div>`).join('') : '<div class="empty-state">Правил пока нет</div>';
        $$('[data-edit-rule]').forEach(button => button.addEventListener('click', () => {
            const rule = rules.find(item => item.id === Number(button.dataset.editRule));
            const options = state.bootstrap.categories.map(category => `<option value="${category.id}" ${category.id === rule.category_id ? 'selected' : ''}>${escapeHtml(category.name)} · ${category.type === 'expense' ? 'расход' : 'доход'}</option>`).join('');
            openEntityForm('Изменить правило', `<label>Текст в описании<input name="pattern" value="${escapeHtml(rule.pattern)}" required maxlength="200"></label><label>Категория<select name="category_id">${options}</select></label><label>Приоритет<input name="priority" type="number" min="0" max="10000" value="${rule.priority}" required></label>`, async data => {
                try { await api(`/api/category-rules/${rule.id}`, { method: 'PATCH', body: data }); toast('Правило обновлено'); closeModals(); loadAutomation(); }
                catch (error) { toast(error.message, 'error'); }
            });
        }));
        $$('[data-toggle-rule]').forEach(button => button.addEventListener('click', async () => {
            try { await api(`/api/category-rules/${button.dataset.toggleRule}`, { method: 'PATCH', body: { is_active: button.dataset.active !== '1' } }); await loadAutomation(); }
            catch (error) { toast(error.message, 'error'); }
        }));
        $$('[data-delete-rule]').forEach(button => button.addEventListener('click', async () => {
            if (!confirm('Удалить правило без возможности восстановления?')) return;
            try { await api(`/api/category-rules/${button.dataset.deleteRule}`, { method: 'DELETE' }); toast('Правило удалено'); await loadAutomation(); }
            catch (error) { toast(error.message, 'error'); }
        }));
        await loadUpcoming();
    }

    async function loadUpcoming() {
        const days = $('#upcomingDays')?.value || 30;
        const data = await api(`/api/upcoming-payments?days=${days}`);
        const container = $('#upcomingTimeline');
        if (!container) return;
        const total = Object.values(data.totals_by_month).reduce((sum, value) => sum + Number(value), 0);
        container.innerHTML = data.items.length ? `<p class="muted">Обязательные расходы: ${money(total)}</p>` + data.items.map(item => `<div class="list-row ${item.status === 'overdue' ? 'is-warning' : ''}"><span>${formatDate(item.date)} · ${escapeHtml(item.title)}${item.status === 'overdue' ? ' · просрочено' : ''}</span><strong>${money(item.amount)}</strong></div>`).join('') : '<div class="empty-state">Платежей на выбранном горизонте нет</div>';
        if (!$('#upcomingDays').dataset.ready) {
            $('#upcomingDays').dataset.ready = '1';
            $('#upcomingDays').addEventListener('change', loadUpcoming);
        }
    }

    async function submitScenario(form) {
        try {
            const result = await api('/api/insights/what-if', { method: 'POST', body: Object.fromEntries(new FormData(form).entries()) });
            $('#scenarioResult').innerHTML = `<div><span>На жизнь</span><strong>${money(result.allocation.life)}</strong></div><div><span>В накопления</span><strong>${money(result.allocation.savings)}</strong></div><div><span>В валюту</span><strong>${money(result.allocation.currency)}</strong></div><div><span>Капитал через ${result.inputs.horizon_months} мес.</span><strong>${money(result.projected_capital)}</strong></div>`;
        } catch (error) { toast(error.message, 'error'); }
    }

    async function loadInsights() {
        const [insights, report, summary] = await Promise.all([api('/api/insights'), api('/api/weekly-report'), api('/api/summary?period=month')]);
        const cushion = insights.cushion;
        $('#cushionRunway').textContent = `${cushion.runway_months} мес. запаса`;
        $('#cushionDetails').innerHTML = `<div class="list-row"><span>Резерв</span><strong>${money(cushion.amount)}</strong></div><div class="list-row"><span>Средние траты в месяц</span><strong>${money(cushion.monthly_burn)}</strong></div><div class="list-row"><span>До цели 3 месяца</span><strong>${money(cushion.gap_3)}</strong></div><div class="list-row"><span>До цели 6 месяцев</span><strong>${money(cushion.gap_6)}</strong></div>`;
        $('#anomalyList').innerHTML = insights.anomalies.length ? insights.anomalies.map(item => `<div class="list-row is-warning"><span>${escapeHtml(item.category_name)} · ${item.kind === 'large_transaction' ? 'крупная операция' : 'рост к среднему'}</span><strong>${money(item.amount || item.current_amount)}</strong></div>`).join('') : '<div class="empty-state">Материальных отклонений не найдено</div>';
        const weeklyMetric = (label, key) => `<div><span>${label} · ${report.deltas[key] >= 0 ? '+' : ''}${report.deltas[key]}% к прошлой</span><strong>${money(report.current_week[key])}</strong></div>`;
        $('#weeklyReport').innerHTML = `<p class="muted">${formatDate(report.current_week.start)} — ${formatDate(report.current_week.end)}</p><div class="result-strip">${weeklyMetric('Доход', 'income')}${weeklyMetric('Расход', 'expense')}${weeklyMetric('Накоплено', 'saved')}${weeklyMetric('В валюту', 'currency_reserved')}</div><h3 class="section-title">Главные категории</h3><div class="compact-list">${report.top_categories.length ? report.top_categories.map(category => `<div class="list-row"><span>${escapeHtml(category.name || 'Без категории')}</span><strong>${money(category.amount)}</strong></div>`).join('') : '<div class="empty-state">Расходов на этой неделе нет</div>'}</div><h3 class="section-title">Три действия</h3><ol class="action-list">${report.actions.map(action => `<li>${escapeHtml(action)}</li>`).join('')}</ol>`;
        const form = $('#whatIfForm');
        if (!form.dataset.ready) {
            form.dataset.ready = '1';
            form.income.value = summary.current.income || summary.forecast.income || 0;
            form.expense.value = summary.current.expense || summary.forecast.expense || state.bootstrap.settings.monthly_life_budget;
            form.savings_percent.value = state.bootstrap.settings.investment_target_percent;
            form.currency_percent.value = state.bootstrap.settings.currency_target_percent;
            form.addEventListener('submit', event => { event.preventDefault(); submitScenario(form); });
            let timer;
            form.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => { if (form.reportValidity()) submitScenario(form); }, 300); });
            submitScenario(form);
        }
    }

    async function refreshBootstrap() {
        state.bootstrap = await api('/api/bootstrap');
        applyRuntimeSettings();
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
            form.account_id.innerHTML = accountOptions(null, false);
            form.target_account_id.innerHTML = accountOptions();
            form.category_id.innerHTML = categoryOptions(form.tx_type.value || 'expense', true);
        }
    }

    async function loadCurrentPage() {
        const content = $('.content');
        content?.setAttribute('aria-busy', 'true');
        try {
            const loaders = {
                dashboard: loadDashboard,
                transactions: loadTransactions,
                investments: loadInvestments,
                purchases: loadPurchases,
                goals: loadGoals,
                people: loadPeople,
                settings: loadSettings,
                recurring: loadRecurring,
                automation: loadAutomation,
                insights: loadInsights,
            };
            await loaders[state.page]?.();
        } catch (error) {
            console.error(error);
            toast(error.message, 'error');
        } finally {
            content?.setAttribute('aria-busy', 'false');
            document.body.classList.remove('app-loading');
        }
    }

    async function init() {
        setupTheme();
        setupCustomSelects();
        if (state.page === 'login') return;
        try {
            await refreshBootstrap();
            state.anchor = state.bootstrap.today;
            setupNavigation();
            setupTransactionModal();
            $('#txTypeFilter')?.addEventListener('change', () => { state.txPage = 1; loadTransactions(); });
            $('#addCategoryBtn')?.addEventListener('click', openCategoryForm);
            $('#addDashboardCategory')?.addEventListener('click', openCategoryForm);
            $('#addPurchaseBtn')?.addEventListener('click', openPurchaseForm);
            $('#addGoalBtn')?.addEventListener('click', openGoalForm);
            $('#addRecurringBtn')?.addEventListener('click', openRecurringForm);
            let searchTimer;
            $('#txSearch')?.addEventListener('input', () => {
                window.clearTimeout(searchTimer);
                searchTimer = window.setTimeout(() => { state.txPage = 1; loadTransactions(); }, 220);
            });
            await loadCurrentPage();
        } catch (error) {
            console.error(error);
            toast(`Не удалось запустить приложение: ${error.message}`, 'error');
            document.body.classList.remove('app-loading');
        }
    }

    init();
})();
