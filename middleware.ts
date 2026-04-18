import { withAuth } from 'next-auth/middleware'

export default withAuth({
  // This tells NextAuth's middleware where to send unauthenticated users
  pages: {
    signIn: '/login',
  },
})

export const config = {
  // Same matcher as before — protect everything except static files
  matcher: [
  // Protect everything EXCEPT:
  //   _next/static, _next/image, favicon.ico — Next.js static assets
  //   api/auth/* — NextAuth's own handler (must stay reachable for login)
  //   api/cron/* — Vercel Cron triggers; no session, auth'd via CRON_SECRET
  //                header inside the handler (see api/cron.py)
  //   api/forecaster, api/forecaster_probe, api/espn_proj — read-only
  //     diagnostic/data endpoints with no user-specific or sensitive data
  '/((?!_next/static|_next/image|favicon.ico|api/auth|api/cron|api/forecaster|api/forecaster_probe|api/espn_proj).*)',
],
}