import type { NextApiRequest, NextApiResponse } from 'next'
import { serialize } from 'cookie'

const COOKIE_NAME = 'skipper_auth'
// Cookie lives for 7 days — re-enter password once a week at most
const MAX_AGE = 60 * 60 * 24 * 7

export default function handler(req: NextApiRequest, res: NextApiResponse) {
  if (req.method !== 'POST') {
    return res.status(405).end()
  }

  const { password } = req.body
  const appPassword = process.env.APP_PASSWORD

  if (!appPassword) {
    return res.status(503).json({ error: 'APP_PASSWORD not configured' })
  }

  if (password !== appPassword) {
    return res.status(401).json({ error: 'Incorrect password' })
  }

  // Set auth cookie
  res.setHeader(
    'Set-Cookie',
    serialize(COOKIE_NAME, appPassword, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: MAX_AGE,
      path: '/',
    })
  )

  return res.status(200).json({ ok: true })
}
