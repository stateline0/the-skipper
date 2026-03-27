import type { AppProps } from 'next/app'
import { SessionProvider } from 'next-auth/react'
import { useRouter } from 'next/router'
import Layout from '../components/Layout'
import '../styles/globals.css'

// Pages that should NOT have the sidebar/header layout
const NO_LAYOUT_PAGES = ['/login']

export default function App({ Component, pageProps: { session, ...pageProps } }: AppProps) {
  const router = useRouter()

  // Check if the current page should skip the layout
  const skipLayout = NO_LAYOUT_PAGES.includes(router.pathname)

  return (
    <SessionProvider session={session}>
      {skipLayout ? (
        // Login page: no layout, just the page itself
        <Component {...pageProps} />
      ) : (
        // Every other page: wrapped in the sidebar + header layout
        <Layout>
          <Component {...pageProps} />
        </Layout>
      )}
    </SessionProvider>
  )
}