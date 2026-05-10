'use client';
import { useState, useRef, useCallback } from 'react';

type Sections = Record<string, string>;

const TABS = [
  { key: '네이버블로그', label: '📝 블로그(SEO)' },
  { key: '인스타그램',   label: '📸 인스타그램' },
  { key: '쓰레드',       label: '🔵 쓰레드' },
  { key: '쇼츠컨셉',     label: '🎬 쇼츠 컨셉' },
  { key: '매물소개서',   label: '📄 매물 소개서' },
  { key: '핵심정보',     label: 'ℹ️ 핵심 정보' },
];

function makeHtml(title: string, content: string, imgB64?: string, imgMime?: string) {
  const imgTag = imgB64
    ? `<img src="data:${imgMime};base64,${imgB64}" style="width:100%;border-radius:12px;margin-bottom:24px;">`
    : '';
  const body = content.split('\n').map(l =>
    l.startsWith('## ') ? `<h2>${l.slice(3)}</h2>`
    : l.startsWith('# ') ? `<h1>${l.slice(2)}</h1>`
    : l.trim() === '' ? '<br>'
    : `<p>${l}</p>`
  ).join('\n');
  return `<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>${title}</title>
<style>body{font-family:'Malgun Gothic',sans-serif;max-width:800px;margin:0 auto;padding:24px;background:#f5f5f5}
.wrap{background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.1)}
.hero{width:100%}.body{padding:36px 40px}
h1{color:#1B3A6B;font-size:26px;margin-bottom:20px}h2{color:#1B3A6B;font-size:20px;margin:24px 0 10px;border-left:4px solid #E8A020;padding-left:12px}
p{color:#333;line-height:1.9;margin-bottom:6px}
.footer{background:#1B3A6B;color:#fff;text-align:center;padding:16px;font-size:13px}</style>
</head><body><div class="wrap"><div class="hero">${imgTag}</div>
<div class="body"><h1>${title}</h1>${body}</div>
<div class="footer">🏠 부동산 AI 콘텐츠 작성기</div></div></body></html>`;
}

function downloadFile(content: string, filename: string, mime: string) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([content], { type: mime }));
  a.download = filename;
  a.click();
}

function copyText(text: string) {
  navigator.clipboard.writeText(text).then(() => alert('복사되었습니다!'));
}

export default function Home() {
  const [docFiles,   setDocFiles]   = useState<File[]>([]);
  const [photoFiles, setPhotoFiles] = useState<File[]>([]);
  const [additional, setAdditional] = useState('');
  const [loading,    setLoading]    = useState('');
  const [sections,   setSections]   = useState<Sections | null>(null);
  const [activeTab,  setActiveTab]  = useState('네이버블로그');
  const [imgGemini,  setImgGemini]  = useState<{b64:string;mime:string} | null>(null);
  const [imgChatGPT, setImgChatGPT] = useState<{b64:string;mime:string} | null>(null);
  const [selectedImg,setSelectedImg]= useState<{b64:string;mime:string} | null>(null);
  const [propImg,    setPropImg]    = useState<{b64:string;mime:string} | null>(null);

  // Recipient
  const [rName,  setRName]  = useState('');
  const [rEmail, setREmail] = useState('');
  const [rPhone, setRPhone] = useState('');
  const [msgOk,  setMsgOk]  = useState('');

  const docRef   = useRef<HTMLInputElement>(null);
  const photoRef = useRef<HTMLInputElement>(null);

  const fileToB64 = useCallback((file: File): Promise<{b64:string;mime:string}> =>
    new Promise(resolve => {
      const r = new FileReader();
      r.onload = () => {
        const result = r.result as string;
        const [header, b64] = result.split(',');
        const mime = header.split(':')[1].split(';')[0];
        resolve({ b64, mime });
      };
      r.readAsDataURL(file);
    }), []);

  const handleGenerate = async () => {
    if (!docFiles.length) { alert('문서 파일을 업로드해주세요.'); return; }
    setSections(null); setImgGemini(null); setImgChatGPT(null); setSelectedImg(null); setPropImg(null);

    const form = new FormData();
    docFiles.forEach(f   => form.append('docs',   f));
    photoFiles.forEach(f => form.append('photos', f));
    form.append('additional', additional);

    // 1. 콘텐츠 생성
    setLoading('🤖 AI가 6가지 콘텐츠 생성 중... (20~50초)');
    const genRes = await fetch('/api/generate', { method:'POST', body: form });
    if (!genRes.ok) { setLoading(''); alert('콘텐츠 생성 실패'); return; }
    const { sections: sec } = await genRes.json() as { sections: Sections };
    setSections(sec);

    // 핵심정보 파싱
    const keyInfo = parseKeyInfo(sec['핵심정보'] ?? '');

    // 2. 매물 사진 처리
    if (photoFiles.length > 0) {
      const first = await fileToB64(photoFiles[0]);
      setPropImg(first);
      setSelectedImg(first);
      setLoading('');
    } else {
      // 두 AI 이미지 동시 생성
      setLoading('🎨 Gemini + ChatGPT 이미지 동시 생성 중... (20~40초)');
      const [gRes, cRes] = await Promise.allSettled([
        fetch('/api/image', { method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ keyInfo, provider:'gemini' }) }),
        fetch('/api/image', { method:'POST', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ keyInfo, provider:'chatgpt' }) }),
      ]);
      if (gRes.status === 'fulfilled' && gRes.value.ok) {
        const d = await gRes.value.json() as {b64:string;mime:string};
        setImgGemini(d); setSelectedImg(d); setPropImg(d);
      }
      if (cRes.status === 'fulfilled' && cRes.value.ok) {
        const d = await cRes.value.json() as {b64:string;mime:string};
        setImgChatGPT(d);
      }
      setLoading('');
    }
  };

  const applyImage = (img: {b64:string;mime:string}) => {
    setSelectedImg(img); setPropImg(img);
  };

  const sendEmail = async () => {
    if (!rEmail) { alert('이메일 주소를 입력하세요.'); return; }
    const res = await fetch('/api/email', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ to: rEmail, subject: `[매물 소개] ${rName}님께`, body: sections?.['매물소개서'] }),
    });
    setMsgOk(res.ok ? '✅ 이메일 전송 완료!' : '❌ 이메일 전송 실패');
  };

  const sendSms = async () => {
    if (!rPhone) { alert('전화번호를 입력하세요.'); return; }
    const res = await fetch('/api/sms', { method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ to: rPhone, message: (sections?.['쓰레드'] ?? '').slice(0,200) }),
    });
    setMsgOk(res.ok ? '✅ 문자 전송 완료!' : '❌ 문자 전송 실패');
  };

  return (
    <div className="max-w-5xl mx-auto p-4 pb-16">
      {/* Header */}
      <div className="text-center py-8">
        <h1 className="text-3xl font-bold text-navy mb-2">🏠 부동산 AI 콘텐츠 작성기</h1>
        <p className="text-gray-500">건축물대장 · 등기부등본 → 블로그 · 인스타 · 쓰레드 · 쇼츠 · 매물소개서 자동 생성</p>
      </div>

      {/* Upload Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100">
          <h2 className="font-semibold text-navy mb-3">📄 문서 업로드</h2>
          <div className="border-2 border-dashed border-gray-200 rounded-lg p-4 text-center cursor-pointer hover:border-navy transition"
               onClick={() => docRef.current?.click()}>
            <p className="text-gray-400 text-sm">PDF · DOCX · HWP · 이미지 (여러 개 가능)</p>
            {docFiles.length > 0 && (
              <p className="text-green-600 text-sm mt-2 font-medium">✅ {docFiles.length}개 선택됨</p>
            )}
          </div>
          <input ref={docRef} type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.bmp,.webp,.docx"
                 className="hidden" onChange={e => setDocFiles(Array.from(e.target.files ?? []))} />
        </div>

        <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100">
          <h2 className="font-semibold text-navy mb-3">📷 매물 사진 업로드 (선택)</h2>
          <div className="border-2 border-dashed border-gray-200 rounded-lg p-4 text-center cursor-pointer hover:border-navy transition"
               onClick={() => photoRef.current?.click()}>
            <p className="text-gray-400 text-sm">없으면 Gemini + ChatGPT가 자동 생성 후 비교</p>
            {photoFiles.length > 0 && (
              <p className="text-green-600 text-sm mt-2 font-medium">✅ {photoFiles.length}개 선택됨</p>
            )}
          </div>
          <input ref={photoRef} type="file" multiple accept=".jpg,.jpeg,.png,.bmp,.webp"
                 className="hidden" onChange={e => setPhotoFiles(Array.from(e.target.files ?? []))} />
        </div>
      </div>

      <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100 mb-4">
        <h2 className="font-semibold text-navy mb-2">✏️ 추가 강조 사항 (선택)</h2>
        <textarea value={additional} onChange={e => setAdditional(e.target.value)} rows={2}
          placeholder="예: 역세권, 주차 가능, 즉시 입주 가능, 리모델링 완료 등"
          className="w-full border border-gray-200 rounded-lg p-3 text-sm resize-none focus:outline-none focus:border-navy" />
      </div>

      <button onClick={handleGenerate} disabled={!!loading}
        className="w-full bg-navy text-white py-4 rounded-xl font-bold text-lg hover:bg-blue-900 disabled:opacity-50 transition mb-6">
        {loading || '🚀 콘텐츠 자동 생성 (6종)'}
      </button>

      {/* Results */}
      {sections && (
        <div>
          {/* Image comparison */}
          {(imgGemini || imgChatGPT) && (
            <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100 mb-4">
              <h2 className="font-semibold text-navy mb-4">🖼️ AI 생성 이미지 비교 · 선택</h2>
              <div className="grid grid-cols-2 gap-4">
                {imgGemini && (
                  <div>
                    <img src={`data:${imgGemini.mime};base64,${imgGemini.b64}`}
                         className="w-full rounded-lg mb-2" alt="Gemini" />
                    <button onClick={() => applyImage(imgGemini)}
                      className={`w-full py-2 rounded-lg text-sm font-medium transition ${selectedImg === imgGemini ? 'bg-navy text-white' : 'bg-gray-100 hover:bg-gray-200'}`}>
                      {selectedImg === imgGemini ? '✅ 선택됨' : 'Gemini 3.1 선택'}
                    </button>
                  </div>
                )}
                {imgChatGPT && (
                  <div>
                    <img src={`data:${imgChatGPT.mime};base64,${imgChatGPT.b64}`}
                         className="w-full rounded-lg mb-2" alt="ChatGPT" />
                    <button onClick={() => applyImage(imgChatGPT)}
                      className={`w-full py-2 rounded-lg text-sm font-medium transition ${selectedImg === imgChatGPT ? 'bg-navy text-white' : 'bg-gray-100 hover:bg-gray-200'}`}>
                      {selectedImg === imgChatGPT ? '✅ 선택됨' : 'ChatGPT 선택'}
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Content Tabs */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 mb-4 overflow-hidden">
            {/* Tab bar */}
            <div className="flex overflow-x-auto border-b border-gray-100 px-4">
              {TABS.map(t => (
                <button key={t.key} onClick={() => setActiveTab(t.key)}
                  className={`px-4 py-3 text-sm whitespace-nowrap transition ${activeTab === t.key ? 'tab-active' : 'tab-inactive'}`}>
                  {t.label}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="p-5">
              {/* Image preview */}
              {propImg && (
                <img src={`data:${propImg.mime};base64,${propImg.b64}`}
                     className="w-full rounded-xl mb-4 max-h-72 object-cover" alt="매물 사진" />
              )}
              {/* Content */}
              <div className="whitespace-pre-wrap text-sm text-gray-700 leading-relaxed mb-4">
                {sections[activeTab]}
              </div>
              {/* Action buttons */}
              <div className="flex flex-wrap gap-2">
                <button onClick={() => {
                  const title = TABS.find(t => t.key === activeTab)?.label ?? activeTab;
                  const html = makeHtml(title, sections[activeTab], propImg?.b64, propImg?.mime);
                  downloadFile(html, `${activeTab}.html`, 'text/html');
                }} className="px-4 py-2 bg-navy text-white rounded-lg text-sm hover:bg-blue-900 transition">
                  📥 HTML 저장
                </button>
                <button onClick={() => copyText(sections[activeTab])}
                  className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700 transition">
                  📋 복사
                </button>
                {activeTab !== '쇼츠컨셉' && activeTab !== '핵심정보' && (
                  <>
                    <a href="https://www.instagram.com/" target="_blank" rel="noopener noreferrer"
                       className="px-4 py-2 bg-pink-500 text-white rounded-lg text-sm hover:bg-pink-600 transition">
                      📸 인스타그램
                    </a>
                    <a href="https://www.facebook.com/" target="_blank" rel="noopener noreferrer"
                       className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm hover:bg-blue-700 transition">
                      👤 페이스북
                    </a>
                    <a href={`https://www.threads.net/intent/post?text=${encodeURIComponent(sections[activeTab].slice(0,500))}`}
                       target="_blank" rel="noopener noreferrer"
                       className="px-4 py-2 bg-gray-800 text-white rounded-lg text-sm hover:bg-gray-900 transition">
                      🔵 쓰레드
                    </a>
                  </>
                )}
              </div>
              {activeTab !== '쇼츠컨셉' && activeTab !== '핵심정보' && (
                <p className="text-xs text-gray-400 mt-2">📋 인스타·페이스북: 복사 후 붙여넣기 | 🔵 쓰레드: 텍스트 자동 입력</p>
              )}
            </div>
          </div>

          {/* Send Section */}
          <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100 mb-4">
            <h2 className="font-semibold text-navy mb-4">📤 전송하기</h2>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="text-xs text-gray-500 block mb-1">이름</label>
                <input value={rName} onChange={e => setRName(e.target.value)}
                  placeholder="홍길동" className="w-full border border-gray-200 rounded-lg p-2 text-sm focus:outline-none focus:border-navy" />
                <label className="text-xs text-gray-500 block mb-1 mt-2">이메일</label>
                <input value={rEmail} onChange={e => setREmail(e.target.value)}
                  placeholder="example@email.com" className="w-full border border-gray-200 rounded-lg p-2 text-sm focus:outline-none focus:border-navy" />
                <label className="text-xs text-gray-500 block mb-1 mt-2">전화번호</label>
                <input value={rPhone} onChange={e => setRPhone(e.target.value)}
                  placeholder="010-1234-5678" className="w-full border border-gray-200 rounded-lg p-2 text-sm focus:outline-none focus:border-navy" />
              </div>
              <div className="flex flex-col gap-2 justify-center">
                <button onClick={sendEmail}
                  className="px-4 py-3 bg-navy text-white rounded-lg text-sm hover:bg-blue-900 transition">
                  📧 이메일 전송 (매물 소개서)
                </button>
                <button onClick={sendSms}
                  className="px-4 py-3 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700 transition">
                  📱 문자 전송 (쓰레드 내용)
                </button>
              </div>
              <div>
                <p className="text-xs text-gray-500 mb-2">💬 카카오톡 (복사 후 붙여넣기)</p>
                <textarea readOnly value={sections['쓰레드']}
                  rows={5} className="w-full border border-gray-200 rounded-lg p-2 text-xs text-gray-600 resize-none" />
              </div>
            </div>
            {msgOk && <p className="mt-3 text-sm font-medium text-green-600">{msgOk}</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function parseKeyInfo(text: string): Record<string,string> {
  const map: Record<string,string> = {};
  for (const line of text.split('\n')) {
    if (!line.includes(':')) continue;
    const [k, ...rest] = line.split(':');
    const key = k.replace(/-/g,'').trim();
    const val = rest.join(':').trim();
    if (key.includes('소재지') || key.includes('주소')) map.address = val;
    else if (key.includes('용도')) map.usage = val;
    else if (key.includes('층수')) map.floors = val;
    else if (key.includes('건축연도')) map.year = val;
    else if (key.includes('구조')) map.structure = val;
  }
  return map;
}
