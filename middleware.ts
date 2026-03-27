import { withAuth } from 'next-auth/middleware'

export default withAuth({
  // This tells NextAuth's middleware where to send unauthenticated users
  pages: {
    signIn: '/login',
  },
})

export const config = {
  // Same matcher as before — protect everything except static files
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
}