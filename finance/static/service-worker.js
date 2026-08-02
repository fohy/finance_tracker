'use strict';

const CACHE_NAME = 'finflow-static-v2';
const OFFLINE_URL = '/static/offline.html';
const STATIC_ASSETS = [
    OFFLINE_URL,
    '/static/css/app.css',
    '/static/js/app.js',
    '/static/icons.svg',
    '/static/caret-down-phosphor-v2.0.8.svg',
    '/static/vendor/jsQR.js',
    '/static/app-icons/favicon.svg',
    '/static/app-icons/app-icon.svg',
    '/static/app-icons/app-icon-192.png',
    '/static/app-icons/app-icon-512.png',
];

self.addEventListener('install', event => {
    event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS)));
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys()
            .then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))))
            .then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const request = event.request;
    if (request.method !== 'GET') return;
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/login') || url.pathname.startsWith('/logout')) {
        event.respondWith(fetch(request));
        return;
    }

    if (request.mode === 'navigate') {
        event.respondWith(fetch(request, { cache: 'no-store' }).catch(() => caches.match(OFFLINE_URL)));
        return;
    }

    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(request).then(cached => cached || fetch(request).then(response => {
                if (response.ok && response.type === 'basic') {
                    const copy = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(request, copy));
                }
                return response;
            }))
        );
    }
});

self.addEventListener('push', event => {
    let payload = {};
    if (event.data) {
        try {
            payload = event.data.json();
        } catch (error) {
            payload = { body: event.data.text() };
        }
    }
    const title = String(payload.title || 'FinFlow').slice(0, 80);
    const body = String(payload.body || 'Есть новое уведомление').slice(0, 240);
    let url = '/';
    try {
        const candidate = new URL(payload.url || payload.data?.url || '/', self.location.origin);
        if (candidate.origin === self.location.origin) url = `${candidate.pathname}${candidate.search}${candidate.hash}`;
    } catch (error) {
        url = '/';
    }
    event.waitUntil(self.registration.showNotification(title, {
        body,
        icon: '/static/app-icons/app-icon-192.png',
        badge: '/static/app-icons/app-icon-192.png',
        tag: payload.tag ? String(payload.tag).slice(0, 80) : undefined,
        data: { url },
    }));
});

self.addEventListener('notificationclick', event => {
    event.notification.close();
    let target = '/';
    try {
        const candidate = new URL(event.notification.data?.url || '/', self.location.origin);
        if (candidate.origin === self.location.origin) target = `${candidate.pathname}${candidate.search}${candidate.hash}`;
    } catch (error) {
        target = '/';
    }
    event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async clients => {
        const client = clients.find(item => new URL(item.url).origin === self.location.origin);
        if (client) {
            if ('navigate' in client) await client.navigate(target);
            return client.focus();
        }
        return self.clients.openWindow(target);
    }));
});
