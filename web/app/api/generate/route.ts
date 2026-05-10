import { NextRequest } from 'next/server';
import OpenAI from 'openai';
import pdf from 'pdf-parse';

export const maxDuration = 60;

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const PROMPT = `아래 부동산 문서를 분석하여 6가지 콘텐츠를 작성하세요.
반드시 아래 구분자를 정확히 사용하세요.

{CONTEXT}{ADDITIONAL}

=== 핵심정보 ===
- 소재지/주소:
- 건물 용도:
- 건축 면적:
- 연면적:
- 토지 면적:
- 층수:
- 건축연도:
- 구조:
- 기타:
=== 끝 ===

=== 네이버블로그 ===
[SEO 제목]: (핵심 키워드 포함, 50자 이내)
[메타 설명]: (150자 이내)

## (H2 소제목1 - 매물 소개)
## (H2 소제목2 - 주요 정보)
## (H2 소제목3 - 특징 및 투자 포인트)
## (H2 소제목4 - 자주 묻는 질문)
(마무리 및 해시태그 20개 이상)
=== 끝 ===

=== 인스타그램 ===
(200~300자, 감성적, 이모지 풍부, 해시태그 12~15개)
=== 끝 ===

=== 쓰레드 ===
(100~150자, 짧고 캐주얼, 해시태그 3~5개)
=== 끝 ===

=== 쇼츠컨셉 ===
[영상 제목]
씬1 (0~10초): 화면/자막
씬2 (10~30초): 화면/자막
씬3 (30~50초): 화면/자막
씬4 (50~60초): 화면/자막
배경음악:
나레이션:
=== 끝 ===

=== 매물소개서 ===
(공식 매물 소개 문서. 제목→개요→주요정보→특징→투자포인트→문의 순서)
=== 끝 ===

⚠️ 소유자 성명 등 개인정보는 절대 포함하지 마세요.`;

function parseSections(text: string) {
  const keys = ['핵심정보','네이버블로그','인스타그램','쓰레드','쇼츠컨셉','매물소개서'];
  const result: Record<string,string> = {};
  for (const key of keys) {
    try {
      const start = text.indexOf(`=== ${key} ===`) + `=== ${key} ===`.length;
      const end   = text.indexOf('=== 끝 ===', start);
      result[key] = text.slice(start, end).trim();
    } catch { result[key] = '생성 실패'; }
  }
  return result;
}

export async function POST(req: NextRequest) {
  const form = await req.formData();
  const docFiles = form.getAll('docs') as File[];
  const photoFiles = form.getAll('photos') as File[];
  const additional = (form.get('additional') as string) || '';

  const texts: string[] = [];
  const visionImgs: { url: string }[] = [];

  for (const file of docFiles) {
    const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
    const buf = Buffer.from(await file.arrayBuffer());
    if (ext === 'pdf') {
      try {
        const { text } = await pdf(buf);
        if (text.trim()) { texts.push(`[${file.name}]\n${text.slice(0,3000)}`); continue; }
      } catch {}
    }
    // image or scanned PDF → vision
    const mime = ['jpg','jpeg'].includes(ext) ? 'image/jpeg' : ext === 'png' ? 'image/png' : 'image/jpeg';
    visionImgs.push({ url: `data:${mime};base64,${buf.toString('base64')}` });
  }

  for (const file of photoFiles) {
    const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
    const mime = ['jpg','jpeg'].includes(ext) ? 'image/jpeg' : `image/${ext}`;
    const buf = Buffer.from(await file.arrayBuffer());
    visionImgs.push({ url: `data:${mime};base64,${buf.toString('base64')}` });
  }

  const combined = texts.join('\n\n---\n\n');
  const context  = combined ? `[문서 내용]\n${combined}\n\n` : '[첨부 이미지에서 정보를 직접 읽어 분석해주세요]\n\n';
  const addStr   = additional ? `[추가 강조사항]: ${additional}\n\n` : '';
  const prompt   = PROMPT.replace('{CONTEXT}', context).replace('{ADDITIONAL}', addStr);

  type MsgContent = string | Array<{type:string; text?:string; image_url?:{url:string; detail:string}}>;
  let content: MsgContent = prompt;
  if (visionImgs.length > 0) {
    content = [
      { type:'text', text: prompt },
      ...visionImgs.map(img => ({ type:'image_url', image_url:{ url: img.url, detail:'high' } })),
    ];
  }

  const res = await openai.chat.completions.create({
    model: 'gpt-4o',
    messages: [{ role:'user', content: content as Parameters<typeof openai.chat.completions.create>[0]['messages'][0]['content'] }],
    max_tokens: 4000,
    temperature: 0.7,
  });

  const sections = parseSections(res.choices[0].message.content ?? '');
  return Response.json({ sections });
}
