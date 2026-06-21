const API = '';

const getToken = () => localStorage.getItem('token');
const setToken = (t) => localStorage.setItem('token', t);
const clearToken = () => localStorage.removeItem('token');

async function req(method, path, body) {
    const headers = { 'Content-Type': 'application/json' };
    const token = getToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;

    const res = await fetch(API + path, {
        method,
        headers,
        body: body ? JSON.stringify(body) : undefined,
    });

    if (res.status === 401) {
        clearToken();
        location.href = '/login.html';
        return null;
    }
    return res;
}

const api = {
    register:    (d) => req('POST',   '/auth/register', d),
    login: (d) => {
        const form = new URLSearchParams();
        form.append('username', d.email);
        form.append('password', d.password);
        // Return response as-is; login.html shows the 401 as an error message.
        // Only non-login pages need the 401→redirect behaviour (handled by req()).
        return fetch('/auth/login', { method: 'POST', body: form });
    },
    me:          ()  => req('GET',    '/auth/me'),
    packages:    ()  => req('GET',    '/packages/'),
    rent:        (id)=> req('POST',   `/rentals/${id}`),
    release:     (id)=> req('DELETE', `/rentals/${id}`),
    logs:        ()  => req('GET',    '/rentals/logs'),
    dashboard:   ()  => req('GET',    '/dashboard/'),
    credentials: ()  => req('GET',    '/dashboard/credentials'),

    // Admin
    adminStats:  ()  => req('GET',    '/admin/stats'),
    adminUsers:  ()  => req('GET',    '/admin/users'),
    adminLogs:   ()  => req('GET',    '/admin/logs'),
};
