import type { NextAuthOptions } from 'next-auth'
import CredentialsProvider from 'next-auth/providers/credentials'

export const authOptions: NextAuthOptions = {
  providers: [
    CredentialsProvider({
      // This is the label shown on the default NextAuth login page
      // We'll build our own login page, but NextAuth still needs this
      name: 'Credentials',

      // These define the fields NextAuth expects on login
      credentials: {
        username: { label: 'Username', type: 'text' },
        password: { label: 'Password', type: 'password' },
      },

      // This function runs when someone tries to log in
      // It receives whatever was submitted in the login form
      // Return a user object if login succeeds, return null if it fails
      async authorize(credentials) {
        const validUsername = process.env.APP_USERNAME
        const validPassword = process.env.APP_PASSWORD

        if (!validUsername || !validPassword) {
          console.error('APP_USERNAME or APP_PASSWORD not set in environment')
          return null
        }

        const usernameMatch = credentials?.username?.trim() === validUsername.trim()
        const passwordMatch = credentials?.password?.trim() === validPassword.trim()

        if (usernameMatch && passwordMatch) {
          // Return a user object — NextAuth stores this in the session token
          // id is required, name is optional but useful
          return { id: '1', name: validUsername }
        }

        // Returning null tells NextAuth the login failed
        return null
      },
    }),
  ],

  // This tells NextAuth where your custom login page lives
  // Without this it would show NextAuth's default login UI
  pages: {
    signIn: '/login',
  },

  // The session strategy:
  // 'jwt' means the session is stored in an encrypted cookie (no database needed)
  // The alternative is 'database', which requires setting up a DB — overkill for now
  session: {
    strategy: 'jwt',
  },
}