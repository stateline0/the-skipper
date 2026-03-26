import { useState, FormEvent } from 'react'
import Head from 'next/head'
import { useRouter } from 'next/router'

export default function Login() {
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const router = useRouter()

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')

    const res = await fetch('/api/auth', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    })

    if (res.ok) {
      router.push('/')
    } else {
      setError('Incorrect password.')
      setLoading(false)
    }
  }

  return (
    <>
      <Head>
        <title>The Skipper — Login</title>
      </Head>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Syne:wght@700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
          font-family: 'Syne', sans-serif;
          background: #f7f9f5;
          min-height: 100vh;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(10px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>

      <div style={{
        width: '100%', maxWidth: 380, padding: '0 24px',
        animation: 'fadeUp 0.4s ease forwards'
      }}>
        {/* Logo mark */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{
            width: 48, height: 48, background: '#0f1a12', borderRadius: 12,
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 24, marginBottom: 14
          }}>⚾</div>
          <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.03em', color: '#0f1a12' }}>
            The Skipper
          </div>
          <div style={{
            fontFamily: "'IBM Plex Mono', monospace", fontSize: 11,
            color: '#6b7a6f', marginTop: 4, letterSpacing: '0.05em'
          }}>
            FANTASY BASEBALL ANALYST
          </div>
        </div>

        {/* Card */}
        <div style={{
          background: '#ffffff', border: '1px solid rgba(15,26,18,0.10)',
          borderRadius: 16, padding: '28px 28px',
          boxShadow: '0 1px 3px rgba(15,26,18,0.08), 0 4px 16px rgba(15,26,18,0.06)'
        }}>
          <form onSubmit={handleSubmit}>
            <label style={{
              display: 'block', fontSize: 11,
              fontFamily: "'IBM Plex Mono', monospace",
              color: '#6b7a6f', letterSpacing: '0.08em',
              marginBottom: 8
            }}>
              PASSWORD
            </label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Enter password"
              autoFocus
              style={{
                width: '100%', fontFamily: "'IBM Plex Mono', monospace",
                fontSize: 14, background: '#f7f9f5',
                border: `1px solid ${error ? '#c0392b' : 'rgba(15,26,18,0.20)'}`,
                borderRadius: 10, padding: '10px 14px',
                color: '#0f1a12', outline: 'none',
                transition: 'border-color 0.15s, box-shadow 0.15s',
                marginBottom: error ? 8 : 16
              }}
              onFocus={e => {
                e.target.style.borderColor = '#2ea865'
                e.target.style.boxShadow = '0 0 0 3px rgba(46,168,101,0.12)'
              }}
              onBlur={e => {
                e.target.style.borderColor = error ? '#c0392b' : 'rgba(15,26,18,0.20)'
                e.target.style.boxShadow = 'none'
              }}
            />

            {error && (
              <div style={{
                fontSize: 12, color: '#c0392b',
                fontFamily: "'IBM Plex Mono', monospace",
                marginBottom: 16
              }}>
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading || !password}
              style={{
                width: '100%', padding: '11px 0',
                background: loading || !password ? '#d0d8cc' : '#0f1a12',
                color: '#ffffff', border: 'none',
                borderRadius: 10, fontSize: 13, fontWeight: 700,
                fontFamily: "'Syne', sans-serif", letterSpacing: '-0.01em',
                cursor: loading || !password ? 'not-allowed' : 'pointer',
                transition: 'background 0.15s'
              }}
            >
              {loading ? 'Checking...' : 'Enter →'}
            </button>
          </form>
        </div>
      </div>
    </>
  )
}
