import Link from 'next/link'
import { useRouter } from 'next/router'
import { signOut, useSession } from 'next-auth/react'

// These are the five main nav items
// 'href' is the URL, 'label' is what shows in the sidebar
const NAV_ITEMS = [
  { href: '/dashboard',        label: 'Dashboard',        icon: '⚡' },
  { href: '/my-team',          label: 'My Team',           icon: '⚾' },
  { href: '/free-agents',      label: 'Free Agents',       icon: '🔍' },
  { href: '/accuracy',         label: 'Accuracy',          icon: '📊' },
  { href: '/recommendations',  label: 'Recommendations',   icon: '🤖' },
]

interface LayoutProps {
  children: React.ReactNode
  weekLabel?: string
  teamName?: string
}

export default function Layout({ children, weekLabel, teamName }: LayoutProps) {
  const router = useRouter()
  const { data: session } = useSession()

  // Handle sign out — NextAuth's signOut() clears the session
  // and redirects to the login page
  async function handleSignOut() {
    await signOut({ callbackUrl: '/login' })
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      minHeight: '100vh',
      background: 'var(--paper)',
    }}>

      {/* ── Top header ── */}
      <header style={{
        background: 'var(--white)',
        borderBottom: '1px solid var(--border)',
        padding: '0 24px',
        position: 'sticky',
        top: 0,
        zIndex: 50,
        height: 56,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        boxShadow: '0 1px 0 var(--border)',
      }}>
        {/* Left: logo + app name */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 28, height: 28,
            background: 'var(--ink)',
            borderRadius: 6,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14,
          }}>⚾</div>
          <span style={{ fontWeight: 700, fontSize: 15, letterSpacing: '-0.02em' }}>
            The Skipper
          </span>
          {weekLabel && (
            <span style={{
              fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--ink-3)',
              background: 'var(--paper-2)', padding: '2px 8px', borderRadius: 99,
              marginLeft: 4,
            }}>{weekLabel}</span>
          )}
        </div>

        {/* Right: team name */}
        {teamName && (
          <span style={{ fontFamily: 'var(--mono)', fontSize: 12, color: 'var(--ink-3)' }}>
            {teamName}
          </span>
        )}
      </header>

      {/* ── Body: sidebar + main content ── */}
      <div style={{ display: 'flex', flex: 1 }}>

        {/* ── Sidebar ── */}
        <nav style={{
          width: 200,
          background: 'var(--white)',
          borderRight: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          padding: '16px 0',
          position: 'sticky',
          top: 56, // lines up below the header
          height: 'calc(100vh - 56px)',
          flexShrink: 0,
        }}>

          {/* Nav links */}
          <div style={{ flex: 1, padding: '0 8px' }}>
            {NAV_ITEMS.map(item => {
              // isActive = true when the current URL matches this nav item
              const isActive = router.pathname === item.href
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '9px 12px',
                    borderRadius: 'var(--radius)',
                    fontSize: 13,
                    fontWeight: isActive ? 600 : 400,
                    color: isActive ? 'var(--ink)' : 'var(--ink-3)',
                    background: isActive ? 'var(--paper-2)' : 'transparent',
                    textDecoration: 'none',
                    marginBottom: 2,
                    transition: 'all 0.15s',
                  }}
                >
                  <span style={{ fontSize: 15 }}>{item.icon}</span>
                  {item.label}
                </Link>
              )
            })}
          </div>

          {/* Sign out button at the bottom of the sidebar */}
          <div style={{ padding: '0 8px', borderTop: '1px solid var(--border)', paddingTop: 12 }}>
            {session && (
              <div style={{
                fontSize: 11, fontFamily: 'var(--mono)',
                color: 'var(--ink-3)', padding: '0 12px', marginBottom: 8,
              }}>
                {session.user?.name}
              </div>
            )}
            <button
              onClick={handleSignOut}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '9px 12px',
                borderRadius: 'var(--radius)',
                fontSize: 13,
                color: 'var(--ink-3)',
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                width: '100%',
                textAlign: 'left',
                transition: 'all 0.15s',
              }}
              onMouseEnter={e => (e.currentTarget.style.color = 'var(--red)')}
              onMouseLeave={e => (e.currentTarget.style.color = 'var(--ink-3)')}
            >
              <span>↩</span> Sign out
            </button>
          </div>
        </nav>

        {/* ── Page content ── */}
        <main style={{
          flex: 1,
          padding: '28px 24px',
          minWidth: 0, // prevents flex children from overflowing
        }}>
          {children}
        </main>

      </div>
    </div>
  )
}