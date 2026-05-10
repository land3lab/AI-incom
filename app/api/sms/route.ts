import { NextRequest } from 'next/server';
import crypto from 'crypto';

export const dynamic = 'force-dynamic';

export async function POST(req: NextRequest) {
  const { to, message } = await req.json();
  const apiKey    = process.env.COOLSMS_API_KEY!;
  const apiSecret = process.env.COOLSMS_API_SECRET!;
  const from      = process.env.COOLSMS_FROM_NUMBER!;

  const date = new Date().toISOString().replace('Z','+00:00').slice(0,23)+'Z';
  const salt = crypto.randomUUID().replace(/-/g,'');
  const sig  = crypto.createHmac('sha256', apiSecret).update(date + salt).digest('hex');

  const res = await fetch('https://api.coolsms.co.kr/messages/v4/send', {
    method: 'POST',
    headers: {
      'Authorization': `HMAC-SHA256 apiKey=${apiKey}, date=${date}, salt=${salt}, signature=${sig}`,
      'Content-Type': 'application/json;charset=UTF-8',
    },
    body: JSON.stringify({ message: { to: to.replace(/-/g,''), from: from.replace(/-/g,''), text: message } }),
  });
  const data = await res.json();
  if (!res.ok) return Response.json({ error: data }, { status: 400 });
  return Response.json({ ok: true });
}
