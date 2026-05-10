import { NextRequest } from 'next/server';
import nodemailer from 'nodemailer';

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  const { to, subject, body } = await req.json();
  const transporter = nodemailer.createTransport({
    service: 'gmail',
    auth: { user: process.env.GMAIL_ADDRESS, pass: process.env.GMAIL_APP_PASSWORD },
  });
  await transporter.sendMail({ from: process.env.GMAIL_ADDRESS, to, subject, text: body });
  return Response.json({ ok: true });
}
