import { NextRequest, NextResponse } from 'next/server'

const PUBLIC_PATHS = ['/login', '/api/auth']
const COOKIE_NAME = 'skipper_auth'

export function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl

  // Always allow login page, auth API, and static assets
  if (
    PUBLIC_PATHS.some(p => pathname.startsWith(p)) ||
    pathname.startsWith('/_next') ||
    pathname.startsWith('/favicon')
  ) {
    return NextResponse.next()
  }

  const appPassword = process.env.APP_PASSWORD

  if (!appPassword) {
    const loginUrl = req.nextUrl.clone()
    loginUrl.pathname = '/login'
    return NextResponse.redirect(loginUrl)
  }

  const authCookie = req.cookies.get(COOKIE_NAME)
  const cookieVal = authCookie ? decodeURIComponent(authCookie.value) : ''

  if (cookieVal === appPassword.trim()) {
    return NextResponse.next()
  }

  const loginUrl = req.nextUrl.clone()
  loginUrl.pathname = '/login'
  return NextResponse.redirect(loginUrl)
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}
