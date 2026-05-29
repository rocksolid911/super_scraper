'use client';

import { useRouter } from 'next/navigation';
import { getUser, logout } from '@/lib/api';
import { useEffect, useState } from 'react';

export default function TopBar() {
  const router = useRouter();
  const [email, setEmail] = useState<string>('');

  useEffect(() => {
    const u = getUser();
    setEmail(u?.email || '');
  }, []);

  return (
    <div className="topbar">
      <div className="brand" style={{ cursor: 'pointer' }} onClick={() => router.push('/')}>
        Super<span>Scraper</span>
      </div>
      <div className="row">
        {email && <span className="muted">{email}</span>}
        <button
          className="secondary"
          onClick={() => {
            logout();
            router.push('/login');
          }}
        >
          Log out
        </button>
      </div>
    </div>
  );
}
