// Thin wrapper around the JSON API (all under /api). JWT is kept in localStorage.
const API = '';

const getToken = () => localStorage.getItem('token');
const setToken = (t) => localStorage.setItem('token', t);
const clearToken = () => localStorage.removeItem('token');

async function req(method, path, body) {
    const headers = {};
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (body !== undefined) headers['Content-Type'] = 'application/json';

    const res = await fetch(API + path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (res.status === 401) {
        clearToken();
        if (!location.pathname.includes('login')) location.href = '/login.html';
        return null;
    }
    return res;
}

// Multipart upload — don't set Content-Type, the browser adds the boundary.
async function upload(file, key) {
    const fd = new FormData();
    fd.append('file', file);
    if (key) fd.append('key', key);
    const headers = {};
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch('/api/objects', { method: 'POST', headers, body: fd });
    if (res.status === 401) { clearToken(); location.href = '/login.html'; return null; }
    return res;
}

// Upload with progress + speed reporting. fetch() can't report upload progress,
// so we use XMLHttpRequest and surface upload.onprogress events to `onProgress`.
// Resolves to { ok, status, json } (json already parsed).
function uploadWithProgress(file, key, onProgress) {
    return new Promise((resolve) => {
        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/objects');
        const token = getToken();
        if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);

        const start = performance.now();
        let lastT = start, lastLoaded = 0;
        xhr.upload.onprogress = (e) => {
            if (!e.lengthComputable || !onProgress) return;
            const now = performance.now();
            // Instantaneous speed over the last tick; fall back to the average.
            const dt = (now - lastT) / 1000;
            const inst = dt > 0 ? (e.loaded - lastLoaded) / dt : 0;
            const avg = (now - start) > 0 ? e.loaded / ((now - start) / 1000) : 0;
            lastT = now; lastLoaded = e.loaded;
            onProgress({
                loaded: e.loaded,
                total: e.total,
                percent: e.total ? (e.loaded / e.total) * 100 : 0,
                speed: inst > 0 ? inst : avg,
                avgSpeed: avg,
            });
        };
        xhr.onload = () => {
            let json = null;
            try { json = JSON.parse(xhr.responseText); } catch (_) {}
            if (xhr.status === 401) { clearToken(); location.href = '/login.html'; }
            resolve({ ok: xhr.status >= 200 && xhr.status < 300, status: xhr.status, json });
        };
        xhr.onerror = () => resolve({ ok: false, status: 0, json: null });

        const fd = new FormData();
        fd.append('file', file);
        if (key) fd.append('key', key);
        xhr.send(fd);
    });
}

const api = {
    register:     (d) => req('POST', '/api/register', d),
    login:        (d) => req('POST', '/api/login', d),
    me:           ()  => req('GET',  '/api/me'),
    packages:     ()  => req('GET',  '/api/packages'),
    subscriptions:()  => req('GET',  '/api/subscriptions'),
    subscribe:    (package_id) => req('POST', '/api/subscriptions', { package_id }),
    credentials:  ()  => req('GET',  '/api/credentials'),
    newCredential:()  => req('POST', '/api/credentials'),
    objects:      ()  => req('GET',  '/api/objects'),
    upload,
    uploadProgress: uploadWithProgress,
    deleteObject: (key) => req('DELETE', '/api/objects/' + encodeURIComponent(key).replace(/%2F/g, '/')),
    downloadUrl:  (key) => req('GET', '/api/objects/' + encodeURIComponent(key).replace(/%2F/g, '/') + '?presigned=1'),
    logs:         ()  => req('GET',  '/api/logs'),
    config:       ()  => req('GET',  '/api/config'),

    // Admin — read
    adminStats:   ()  => req('GET', '/api/admin/stats'),
    adminUsers:   ()  => req('GET', '/api/admin/users'),
    adminLogs:    (userId) => req('GET', '/api/admin/logs' + (userId ? `?user_id=${userId}` : '')),
    adminPackages:()  => req('GET', '/api/admin/packages'),
    // Admin — package CRUD
    adminCreatePackage: (d)     => req('POST',   '/api/admin/packages', d),
    adminUpdatePackage: (id, d) => req('PUT',    `/api/admin/packages/${id}`, d),
    adminDeletePackage: (id)    => req('DELETE', `/api/admin/packages/${id}`),
    // Admin — user moderation
    adminSuspendUser:   (id) => req('POST',   `/api/admin/users/${id}/suspend`),
    adminActivateUser:  (id) => req('POST',   `/api/admin/users/${id}/activate`),
    adminDeleteUser:    (id) => req('DELETE', `/api/admin/users/${id}`),
    adminAddCredit:     (id, amount) => req('POST', `/api/admin/users/${id}/credit`, { amount }),
};

// Format a byte count as a human-readable size.
function fmtBytes(bytes) {
    if (bytes == null) return '—';
    if (bytes === 0) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(1024));
    return (bytes / Math.pow(1024, i)).toFixed(i === 0 ? 0 : 1) + ' ' + units[i];
}
