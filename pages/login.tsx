import { useState, useEffect } from 'react'
import { signIn, useSession } from 'next-auth/react'
import { useRouter } from 'next/router'

export default function LoginPage() {
  const { data: session, status } = useSession()
  const router = useRouter()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (status === 'authenticated') {
      router.push('/')
    }
  }, [status, router])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError('')

    const result = await signIn('credentials', {
      username,
      password,
      redirect: false,
    })

    if (result?.ok) {
      router.push('/')
    } else {
      setError('Invalid username or password')
      setLoading(false)
    }
  }

  if (status === 'loading' || status === 'authenticated') {
    return null
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '100vh',
      fontFamily: 'sans-serif',
    }}>
      <h1 style={{ marginBottom: '8px' }}>⚾ The Skipper</h1>
      <p style={{ marginBottom: '32px', color: '#666' }}>Fantasy Baseball Assistant</p>

      <form
        onSubmit={handleSubmit}
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
          width: '300px',
        }}
      >
        <input
          type="text"
          placeholder="Username"
          value={username}
          onChange={e => setUsername(e.target.value)}
          autoComplete="username"
          style={{ padding: '10px', fontSize: '16px', borderRadius: '6px', border: '1px solid #ccc' }}
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          autoComplete="current-password"
          style={{ padding: '10px', fontSize: '16px', borderRadius: '6px', border: '1px solid #ccc' }}
        />

        {error && (
          <p style={{ color: 'red', margin: 0, fontSize: '14px' }}>{error}</p>
        )}

        <button
          type="submit"
          disabled={loading}
          style={{
            padding: '10px',
            fontSize: '16px',
            borderRadius: '6px',
            border: 'none',
            background: '#2563eb',
            color: 'white',
            cursor: loading ? 'not-allowed' : 'pointer',
            opacity: loading ? 0.7 : 1,
          }}
        >
          {loading ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  )
}