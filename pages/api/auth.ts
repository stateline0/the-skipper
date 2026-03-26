import type { NextApiRequest, NextApiResponse } from 'next'

const COOKIE_NAME = 'skipper_auth'
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

  const trimmedInput = (password || '').trim()
  const trimmedStored = appPassword.trim()

  if (trimmedInput !== trimmedStored) {
    return res.status(401).json({ error: 'Incorrect password' })
  }

  const cookieValue = `${COOKIE_NAME}=${encodeURIComponent(trimmedStored)}; Max-Age=${MAX_AGE}; Path=/; HttpOnly; SameSite=Lax; Secure`
  res.setHeader('Set-Cookie', cookieValue)

  return res.status(200).json({ ok: true })
}
