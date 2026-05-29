'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { login, register, ApiError } from '@/lib/api';

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      if (mode === 'register') {
        await register({
          email,
          username: username || email.split('@')[0],
          password,
          password_confirm: confirm,
        });
      }
      await login(email, password);
      router.push('/');
    } catch (err) {
      const e = err as ApiError;
      setError(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container" style={{ maxWidth: 420, marginTop: 80 }}>
      <div className="brand" style={{ fontSize: 22, marginBottom: 20 }}>
        Super<span>Scraper</span>
      </div>
      <div className="card">
        <h1>{mode === 'login' ? 'Log in' : 'Create account'}</h1>
        <form onSubmit={submit}>
          <label>Email</label>
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          {mode === 'register' && (
            <>
              <label>Username</label>
              <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="(optional)" />
            </>
          )}
          <label>Password</label>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          {mode === 'register' && (
            <>
              <label>Confirm password</label>
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
            </>
          )}
          {error && <div className="error">{error}</div>}
          <div style={{ marginTop: 16 }}>
            <button type="submit" disabled={busy}>
              {busy ? '...' : mode === 'login' ? 'Log in' : 'Sign up'}
            </button>
          </div>
        </form>
        <p className="notice" style={{ marginTop: 16 }}>
          {mode === 'login' ? "No account? " : 'Have an account? '}
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              setMode(mode === 'login' ? 'register' : 'login');
              setError('');
            }}
          >
            {mode === 'login' ? 'Register' : 'Log in'}
          </a>
        </p>
      </div>
    </div>
  );
}
