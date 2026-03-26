import { NextRequest, NextResponse } from 'next/server'

const PUBLIC_PATHS = ['/login']
const COOKIE_NAME = 'skipper_auth'

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl

  // Always allow login page and static assets
  if (
    PUBLIC_PATHS.includes(pathname) ||
    pathname.startsWith('/_next') ||
    pathname.startsWith('/favicon')
  ) {
    return NextResponse.next()
  }

  // Check auth cookie
  const authCookie = req.cookies.get(COOKIE_NAME)
  const appPassword = process.env.APP_PASSWORD

  if (!appPassword) {
    // No password set in env — fail closed, show a clear error
    return new NextResponse('APP_PASSWORD environment variable is not set.', { status: 503 })
  }

  if (authCookie?.value === appPassword) {
    return NextResponse.next()
  }

  // Not authenticated — redirect to login
  const loginUrl = req.nextUrl.clone()
  loginUrl.pathname = '/login'
  return NextResponse.redirect(loginUrl)
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
