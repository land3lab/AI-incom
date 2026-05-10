import { NextRequest } from 'next/server';
import OpenAI from 'openai';
import { GoogleGenAI } from '@google/genai';

export const maxDuration = 60;

const openai  = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
const gemini  = new GoogleGenAI({ apiKey: process.env.GOOGLE_API_KEY ?? '' });

function buildPrompt(keyInfo: Record<string,string>) {
  return `Professional real estate exterior photograph. Korean building in ${keyInfo.address ?? '서울'}. `
    + `${keyInfo.usage ?? '건물'}, ${keyInfo.floors ?? ''}. `
    + `Clean modern architecture, bright daylight, high quality realistic photo, no people, no text.`;
}

export async function POST(req: NextRequest) {
  const { keyInfo, provider } = await req.json() as { keyInfo: Record<string,string>; provider: string };
  const prompt = buildPrompt(keyInfo);

  if (provider === 'chatgpt') {
    const res = await openai.images.generate({
      model: 'gpt-image-1', prompt, size: '1024x1024', quality: 'low', n: 1,
    });
    const b64 = res.data[0].b64_json!;
    return Response.json({ b64, mime: 'image/png' });
  }

  // Gemini
  const res = await gemini.models.generateContent({
    model: 'gemini-3.1-flash-image-preview',
    contents: prompt,
    config: { responseModalities: ['IMAGE'] } as never,
  });
  for (const part of (res.candidates?.[0]?.content?.parts ?? [])) {
    if ((part as never as {inlineData?: {data:string; mimeType:string}}).inlineData) {
      const { data, mimeType } = (part as never as {inlineData: {data:string; mimeType:string}}).inlineData;
      return Response.json({ b64: data, mime: mimeType });
    }
  }
  return Response.json({ error: '이미지 생성 실패' }, { status: 500 });
}
