import streamlit as st
import pdfplumber
import fitz  # PyMuPDF
import openai
import os, io, base64, tempfile, subprocess, zipfile, urllib.parse
import smtplib, hashlib, hmac, uuid as _uuid
from concurrent.futures import ThreadPoolExecutor
import requests
import streamlit.components.v1 as components
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

try:
    from docx import Document as DocxDocument
    DOCX_OK = True
except ImportError:
    DOCX_OK = False

load_dotenv()

st.set_page_config(page_title="부동산 AI 콘텐츠 작성기", page_icon="🏠", layout="wide")
st.title("🏠 부동산 AI 콘텐츠 작성기")
st.caption("건축물대장 · 등기부등본 → 블로그(SEO) · 인스타 · 쓰레드 · 쇼츠 · 매물소개서 · 카드뉴스 자동 생성")

api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.error("⚠️ OPENAI_API_KEY가 설정되지 않았습니다.")
    st.stop()

client = openai.OpenAI(api_key=api_key)

IMAGE_EXTS = {"jpg", "jpeg", "png", "bmp", "tiff", "tif", "webp"}
MIME_MAP = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "bmp": "image/bmp", "tiff": "image/tiff", "tif": "image/tiff", "webp": "image/webp"
}

# ── 폰트 경로 ─────────────────────────────────────────────────────────────────

FONT_PATHS = {
    "regular": [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/NanumGothic.ttf",
        "C:/Windows/Fonts/gulim.ttc",
    ],
    "bold": [
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/NanumGothicBold.ttf",
        "C:/Windows/Fonts/gulim.ttc",
    ],
}

def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for path in FONT_PATHS["bold" if bold else "regular"]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ── 파일 처리 ─────────────────────────────────────────────────────────────────

def pdf_extract_text(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages).strip()

def pdf_to_images(data: bytes, max_pages: int = 5) -> list:
    doc = fitz.open(stream=data, filetype="pdf")
    return [(base64.b64encode(doc[i].get_pixmap(matrix=fitz.Matrix(2,2)).tobytes("png")).decode(), "image/png")
            for i in range(min(len(doc), max_pages))]

def docx_extract_text(data: bytes) -> str:
    doc = DocxDocument(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())

def hwp_extract_text(data: bytes, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(data); tmp_path = tmp.name
    try:
        r = subprocess.run(["hwp5txt", tmp_path], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""
    finally:
        try: os.unlink(tmp_path)
        except Exception: pass

def process_doc_file(file) -> tuple:
    ext = file.name.lower().rsplit(".", 1)[-1]
    data = file.read()
    texts, images = [], []
    if ext == "pdf":
        text = pdf_extract_text(data)
        if text:
            texts.append(f"[{file.name}]\n{text[:3000]}")
        else:
            st.info(f"📷 {file.name} — 스캔 이미지, 비전 모드로 분석합니다.")
            images.extend(pdf_to_images(data))
    elif ext in IMAGE_EXTS:
        images.append((base64.b64encode(data).decode(), MIME_MAP.get(ext, "image/png")))
    elif ext == "docx" and DOCX_OK:
        text = docx_extract_text(data)
        if text: texts.append(f"[{file.name}]\n{text[:3000]}")
    elif ext in ("hwp", "hwpx"):
        text = hwp_extract_text(data, f".{ext}")
        if text: texts.append(f"[{file.name}]\n{text[:3000]}")
        else: st.warning(f"⚠️ {file.name} HWP 추출 실패. PDF로 변환 후 업로드해 주세요.")
    else:
        st.warning(f"⚠️ {file.name} — 지원하지 않는 형식")
    return texts, images


# ── AI 콘텐츠 생성 ────────────────────────────────────────────────────────────

PROMPT = """아래 부동산 문서를 분석하여 6가지 콘텐츠를 작성하세요.
반드시 아래 구분자를 정확히 사용하세요.

{context}{additional}

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
아래 SEO 형식에 맞게 1500~2000자로 작성하세요.

[SEO 제목]: (핵심 키워드(지역명+매물유형) 포함, 50자 이내)
[메타 설명]: (검색 결과에 표시될 요약, 150자 이내, 핵심 키워드 포함)

## (H2 소제목1 - 매물 소개)
(도입부 - 지역명·매물유형 키워드 자연스럽게 포함)

## (H2 소제목2 - 주요 정보)
(건물 정보 상세 설명 - 이모지 활용)

## (H2 소제목3 - 특징 및 투자 포인트)
(장점, 활용 방안, 주변 환경)

## (H2 소제목4 - 자주 묻는 질문)
Q: (매물 관련 예상 질문)
A: (친절한 답변)

(마무리 - 문의 안내)
(해시태그 20개 이상)
=== 끝 ===

=== 인스타그램 ===
(200~300자. 감성적. 이모지 풍부. 개행 활용. 해시태그 12~15개.)
=== 끝 ===

=== 쓰레드 ===
(100~150자. 짧고 캐주얼. 핵심만. 해시태그 3~5개.)
=== 끝 ===

=== 쇼츠컨셉 ===
[영상 제목]
[컨셉 설명]

씬1 (0~10초): 화면 내용 / 자막
씬2 (10~30초): 화면 내용 / 자막
씬3 (30~50초): 화면 내용 / 자막
씬4 (50~60초): 화면 내용 / 자막

배경음악:
전체 나레이션:
=== 끝 ===

=== 매물소개서 ===
(공식 매물 소개 문서. 제목→개요→주요정보→특징→투자포인트→문의 순서. 전문적 문체.)
=== 끝 ===

⚠️ 소유자 성명 등 개인정보는 절대 포함하지 마세요."""

SECTION_KEYS = ["핵심정보", "네이버블로그", "인스타그램", "쓰레드", "쇼츠컨셉", "매물소개서"]

def parse_sections(text: str) -> dict:
    result = {}
    for key in SECTION_KEYS:
        try:
            start = text.index(f"=== {key} ===") + len(f"=== {key} ===")
            end   = text.index("=== 끝 ===", start)
            result[key] = text[start:end].strip()
        except ValueError:
            result[key] = "(생성 실패 — 다시 시도해주세요)"
    return result

def parse_key_info_dict(text: str) -> dict:
    mapping = {
        "address":       ["소재지", "주소"],
        "usage":         ["건물 용도", "용도"],
        "building_area": ["건축 면적"],
        "total_area":    ["연면적"],
        "land_area":     ["토지 면적"],
        "floors":        ["층수"],
        "year":          ["건축연도", "건축년도"],
        "structure":     ["구조"],
    }
    result = {k: "확인 불가" for k in mapping}
    for line in text.split("\n"):
        if ":" not in line:
            continue
        key_part, _, val = line.partition(":")
        key_part = key_part.strip().lstrip("-").strip()
        val = val.strip()
        if not val or val == "확인 불가":
            continue
        for field, keywords in mapping.items():
            if any(kw in key_part for kw in keywords):
                result[field] = val
                break
    return result

def call_openai(all_texts: list, all_images: list, prop_images: list, additional_info: str) -> dict:
    combined = "\n\n---\n\n".join(all_texts) if all_texts else ""
    context  = f"[문서 내용]\n{combined}\n\n" if combined else "[첨부 이미지에서 정보를 직접 읽어 분석해주세요]\n\n"
    additional = f"[추가 강조사항]: {additional_info}\n\n" if additional_info else ""
    prompt   = PROMPT.format(context=context, additional=additional)

    # 문서 이미지 + 매물 사진 모두 vision으로 전달
    vision_images = all_images + prop_images

    if not vision_images:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000, temperature=0.7)
    else:
        content = [{"type": "text", "text": prompt}]
        for b64, mime in vision_images:
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}", "detail": "high"}})
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": content}],
            max_tokens=4000, temperature=0.7)
    return parse_sections(response.choices[0].message.content)


# ── AI 이미지 생성 ────────────────────────────────────────────────────────────

def _build_image_prompt(key_info: dict) -> str:
    address = key_info.get("address", "서울")
    usage   = key_info.get("usage", "건물")
    floors  = key_info.get("floors", "")
    return (
        f"Professional real estate exterior photograph. Korean building in {address}. "
        f"{usage}, {floors}. Clean modern architecture, bright daylight, "
        f"high quality realistic photo, no people, no text."
    )

def generate_ai_image_gemini(key_info: dict) -> bytes | None:
    google_api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    if not google_api_key:
        st.warning("⚠️ GOOGLE_API_KEY가 .env에 없습니다.")
        return None
    try:
        from google import genai as google_genai
        from google.genai import types as gtypes
        g = google_genai.Client(api_key=google_api_key)
        resp = g.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=_build_image_prompt(key_info),
            config=gtypes.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )
        for part in resp.candidates[0].content.parts:
            if part.inline_data:
                return part.inline_data.data
        return None
    except Exception as e:
        st.warning(f"⚠️ Gemini 이미지 생성 실패: {e}")
        return None

def generate_ai_image_chatgpt(key_info: dict) -> bytes | None:
    try:
        resp = client.images.generate(
            model="gpt-image-1",
            prompt=_build_image_prompt(key_info),
            size="1024x1024",
            quality="low",
            n=1,
        )
        return base64.b64decode(resp.data[0].b64_json)
    except Exception as e:
        st.warning(f"⚠️ ChatGPT 이미지 생성 실패: {e}")
        return None

def generate_ai_image(key_info: dict, provider: str) -> bytes | None:
    if provider == "ChatGPT (gpt-image-1)":
        return generate_ai_image_chatgpt(key_info)
    return generate_ai_image_gemini(key_info)


# ── 카드뉴스 생성 (Pillow) ────────────────────────────────────────────────────

W, H = 1080, 1080
NAVY  = (25,  58, 107)
GOLD  = (220, 155,  30)
WHITE = (255, 255, 255)
LIGHT = (245, 247, 252)
DARK  = (28,  28,  48)
GRAY  = (120, 125, 145)

def draw_text_wrapped(draw, text, font, x, y, max_w, color, line_gap=8):
    fh = draw.textbbox((0,0), "가", font=font)[3]
    lh = fh + line_gap
    line = ""
    for ch in text:
        test = line + ch
        w = draw.textlength(test, font=font)
        if w > max_w:
            draw.text((x, y), line, font=font, fill=color)
            y += lh
            line = ch
        else:
            line = test
    if line:
        draw.text((x, y), line, font=font, fill=color)
        y += lh
    return y

def fit_image(img_pil: Image.Image, w: int, h: int) -> Image.Image:
    ratio = max(w / img_pil.width, h / img_pil.height)
    new_w = int(img_pil.width * ratio)
    new_h = int(img_pil.height * ratio)
    img_pil = img_pil.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top  = (new_h - h) // 2
    return img_pil.crop((left, top, left + w, top + h))

def make_card1_cover(prop_img_pil, key_info: dict) -> Image.Image:
    card = Image.new("RGB", (W, H), NAVY)
    if prop_img_pil:
        bg = fit_image(prop_img_pil, W, H)
        card.paste(bg)
        overlay = Image.new("RGBA", (W, H), (10, 20, 50, 180))
        card = card.convert("RGBA")
        card.alpha_composite(overlay)
        card = card.convert("RGB")
    d = ImageDraw.Draw(card)
    d.rectangle([(0,0),(W,14)], fill=GOLD)
    d.rectangle([(0,H-14),(W,H)], fill=GOLD)

    f32 = get_font(32)
    f60 = get_font(60, bold=True)
    f38 = get_font(38, bold=True)
    f28 = get_font(28)

    d.text((60, 40), "🏠  부동산 매물 소개", font=f32, fill=GOLD)
    y = H // 2 - 80
    y = draw_text_wrapped(d, key_info.get("address",""), f60, 60, y, W-120, WHITE, 12)
    y += 20
    draw_text_wrapped(d, key_info.get("usage",""), f38, 60, y, W-120, GOLD, 8)

    d.text((60, H-80), "문의: [연락처를 입력하세요]", font=f28, fill=WHITE)
    return card

def make_card2_info(key_info: dict) -> Image.Image:
    card = Image.new("RGB", (W, H), LIGHT)
    d = ImageDraw.Draw(card)
    d.rectangle([(0,0),(W,160)], fill=NAVY)
    d.rectangle([(0,148),(W,160)], fill=GOLD)

    f_h = get_font(50, bold=True)
    f_l = get_font(30)
    f_v = get_font(34, bold=True)

    d.text((50, 52), "📋  매물 주요 정보", font=f_h, fill=WHITE)

    items = [
        ("📍", "소재지",   key_info.get("address","확인 불가")),
        ("🏢", "건물 용도", key_info.get("usage","확인 불가")),
        ("📐", "건축 면적", key_info.get("building_area","확인 불가")),
        ("🌿", "토지 면적", key_info.get("land_area","확인 불가")),
        ("🏗️", "건축연도",  key_info.get("year","확인 불가")),
        ("🏬", "층수",     key_info.get("floors","확인 불가")),
        ("🧱", "구조",     key_info.get("structure","확인 불가")),
    ]
    y = 185
    for emoji, label, value in items:
        d.rectangle([(30, y),(W-30, y+108)], fill=WHITE)
        d.text((55,  y+14), emoji,  font=f_l, fill=NAVY)
        d.text((120, y+14), label,  font=f_l, fill=GRAY)
        draw_text_wrapped(d, value[:50], f_v, 120, y+56, W-180, DARK)
        y += 118
    d.rectangle([(0,H-14),(W,H)], fill=GOLD)
    return card

def make_card3_features(sections: dict) -> Image.Image:
    card = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(card)
    d.rectangle([(0,0),(W,160)], fill=NAVY)
    d.rectangle([(0,148),(W,160)], fill=GOLD)
    d.text((50, 52), "✨  건물 특징", font=get_font(50, bold=True), fill=WHITE)

    blog_text = sections.get("네이버블로그", "")
    lines = [l.strip() for l in blog_text.split("\n")
             if l.strip() and not l.startswith("#") and not l.startswith("[") and len(l.strip()) > 10]
    lines = lines[:8]

    f = get_font(34)
    y = 190
    for line in lines:
        d.rectangle([(30, y),(48, y+34)], fill=GOLD)
        y = draw_text_wrapped(d, line[:60], f, 65, y, W-110, DARK, 8)
        y += 16
        if y > H - 80:
            break
    d.rectangle([(0,H-14),(W,H)], fill=GOLD)
    return card

def make_card4_investment(sections: dict) -> Image.Image:
    card = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(card)
    d.rectangle([(0,0),(W,14)], fill=GOLD)

    d.text((50, 50), "💡  투자 포인트", font=get_font(52, bold=True), fill=GOLD)

    intro_text = sections.get("매물소개서", "")
    lines = [l.strip() for l in intro_text.split("\n")
             if l.strip() and ("투자" in l or "특징" in l or "장점" in l or "포인트" in l or "•" in l or "-" in l)]
    lines = lines[:7]

    f = get_font(36)
    y = 160
    for line in lines:
        d.rectangle([(50, y+12),(62, y+44)], fill=GOLD)
        y = draw_text_wrapped(d, line.lstrip("-•· ").strip()[:55], f, 80, y, W-130, WHITE, 10)
        y += 20
        if y > H - 100:
            break

    d.text((50, H-80), "더 많은 정보는 문의주세요 😊", font=get_font(32), fill=GOLD)
    d.rectangle([(0,H-14),(W,H)], fill=GOLD)
    return card

def make_card5_contact(prop_img_pil, key_info: dict) -> Image.Image:
    card = Image.new("RGB", (W, H), LIGHT)
    d = ImageDraw.Draw(card)
    d.rectangle([(0,0),(W,14)], fill=NAVY)

    if prop_img_pil:
        thumb = fit_image(prop_img_pil, 360, 260)
        card.paste(thumb, (W-390, 50))

    d.text((50, 40), "📞  문의 안내", font=get_font(52, bold=True), fill=NAVY)

    f40 = get_font(40, bold=True)
    f34 = get_font(34)
    f30 = get_font(30)

    y = 180
    d.rectangle([(30, y),(W-30, y+300)], fill=WHITE)
    d.text((60, y+20), "📍  매물 위치", font=f34, fill=GRAY)
    draw_text_wrapped(d, key_info.get("address",""), f40, 60, y+65, W-100, DARK)

    y += 340
    d.rectangle([(30, y),(W-30, y+160)], fill=NAVY)
    d.text((60, y+20), "연락처", font=f34, fill=GOLD)
    d.text((60, y+72), "[연락처를 입력하세요]", font=get_font(44, bold=True), fill=WHITE)

    y += 200
    msgs = ["💬 카카오톡 문의 환영", "📧 이메일 문의 가능", "⏰ 평일 09:00 ~ 18:00"]
    for msg in msgs:
        d.text((60, y), msg, font=f30, fill=GRAY)
        y += 50

    d.text((50, H-70), "🏠  부동산 전문가와 함께하세요", font=f34, fill=NAVY)
    d.rectangle([(0,H-14),(W,H)], fill=GOLD)
    return card

def create_card_news(sections: dict, key_info: dict, prop_img_bytes: bytes | None) -> list:
    prop_img_pil = None
    if prop_img_bytes:
        try:
            prop_img_pil = Image.open(io.BytesIO(prop_img_bytes)).convert("RGB")
        except Exception:
            pass
    return [
        make_card1_cover(prop_img_pil, key_info),
        make_card2_info(key_info),
        make_card3_features(sections),
        make_card4_investment(sections),
        make_card5_contact(prop_img_pil, key_info),
    ]

def make_html(title: str, content: str, prop_img_bytes: bytes | None) -> str:
    img_tag = ""
    if prop_img_bytes:
        b64 = base64.b64encode(prop_img_bytes).decode()
        img_tag = f'<img src="data:image/jpeg;base64,{b64}" alt="매물 사진">'

    lines = content.split("\n")
    html_lines = []
    for line in lines:
        if line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            html_lines.append(f"<p>{line}</p>")
    body = "\n".join(html_lines)

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0 }}
body {{ font-family:'Malgun Gothic','맑은 고딕',sans-serif; background:#f0f2f6; padding:24px }}
.wrap {{ max-width:800px; margin:0 auto; background:#fff; border-radius:16px;
         box-shadow:0 4px 24px rgba(0,0,0,.1); overflow:hidden }}
.hero img {{ width:100%; display:block; max-height:480px; object-fit:cover }}
.body {{ padding:36px 40px }}
h1 {{ color:#1b3a6b; font-size:26px; margin-bottom:20px; line-height:1.4 }}
h2 {{ color:#1b3a6b; font-size:20px; margin:28px 0 10px; border-left:4px solid #e8a020;
      padding-left:12px }}
h3 {{ color:#444; font-size:17px; margin:18px 0 8px }}
p  {{ color:#333; font-size:15px; line-height:1.9; margin-bottom:6px }}
.footer {{ background:#1b3a6b; color:#fff; text-align:center; padding:16px;
           font-size:13px; margin-top:32px }}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">{img_tag}</div>
  <div class="body">
    <h1>{title}</h1>
    {body}
  </div>
  <div class="footer">🏠 부동산 AI 콘텐츠 작성기</div>
</div>
</body>
</html>"""

def cards_to_zip(cards: list) -> bytes:
    buf = io.BytesIO()
    names = ["01_커버", "02_주요정보", "03_건물특징", "04_투자포인트", "05_문의안내"]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for card, name in zip(cards, names):
            img_buf = io.BytesIO()
            card.save(img_buf, format="PNG")
            zf.writestr(f"카드뉴스_{name}.png", img_buf.getvalue())
    return buf.getvalue()

def create_master_zip(sections: dict, cards: list, prop_img_bytes: bytes | None) -> bytes:
    buf = io.BytesIO()
    card_names = ["01_커버", "02_주요정보", "03_건물특징", "04_투자포인트", "05_문의안내"]
    text_files = {
        "블로그(SEO).txt":  sections.get("네이버블로그", ""),
        "인스타그램.txt":   sections.get("인스타그램", ""),
        "쓰레드.txt":       sections.get("쓰레드", ""),
        "쇼츠_컨셉.txt":    sections.get("쇼츠컨셉", ""),
        "매물_소개서.txt":  sections.get("매물소개서", ""),
        "핵심_정보.txt":    sections.get("핵심정보", ""),
    }
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fname, content in text_files.items():
            zf.writestr(f"텍스트/{fname}", content.encode("utf-8"))
        for card, name in zip(cards, card_names):
            img_buf = io.BytesIO()
            card.save(img_buf, format="PNG")
            zf.writestr(f"카드뉴스/카드뉴스_{name}.png", img_buf.getvalue())
        if prop_img_bytes:
            zf.writestr("매물_사진.jpg", prop_img_bytes)
    return buf.getvalue()


# ── 전송 함수 ─────────────────────────────────────────────────────────────────

# ── Instagram Graph API 업로드 ────────────────────────────────────────────────

def upload_to_imgbb(img_bytes: bytes) -> str:
    api_key = os.getenv("IMGBB_API_KEY", "").strip()
    if not api_key:
        raise ValueError("IMGBB_API_KEY가 .env에 없습니다. imgbb.com에서 무료 발급하세요.")
    resp = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": api_key, "image": base64.b64encode(img_bytes).decode(), "expiration": 600},
        timeout=30,
    )
    data = resp.json()
    if not data.get("success"):
        raise Exception(f"imgbb 업로드 실패: {data}")
    return data["data"]["url"]

def post_to_instagram(img_bytes: bytes, caption: str) -> str:
    token    = os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
    ig_id    = os.getenv("INSTAGRAM_USER_ID", "").strip()
    if not token or not ig_id:
        raise ValueError("INSTAGRAM_ACCESS_TOKEN 또는 INSTAGRAM_USER_ID가 .env에 없습니다.")

    image_url = upload_to_imgbb(img_bytes)

    # 미디어 컨테이너 생성
    r1 = requests.post(
        f"https://graph.facebook.com/v21.0/{ig_id}/media",
        data={"image_url": image_url, "caption": caption, "access_token": token},
        timeout=30,
    )
    r1_json = r1.json()
    if "error" in r1_json:
        raise Exception(f"컨테이너 생성 실패: {r1_json['error']['message']}")

    # 게시
    r2 = requests.post(
        f"https://graph.facebook.com/v21.0/{ig_id}/media_publish",
        data={"creation_id": r1_json["id"], "access_token": token},
        timeout=30,
    )
    r2_json = r2.json()
    if "error" in r2_json:
        raise Exception(f"게시 실패: {r2_json['error']['message']}")
    return r2_json.get("id", "")


def send_email(recipient_email: str, subject: str, body: str):
    sender   = os.getenv("GMAIL_ADDRESS", "").strip()
    password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not sender or not password:
        raise ValueError("GMAIL_ADDRESS 또는 GMAIL_APP_PASSWORD가 .env에 없습니다.")
    msg = MIMEMultipart()
    msg["From"], msg["To"], msg["Subject"] = sender, recipient_email, subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, password)
        s.send_message(msg)

def send_sms(to_number: str, message: str):
    api_key    = os.getenv("COOLSMS_API_KEY","").strip()
    api_secret = os.getenv("COOLSMS_API_SECRET","").strip()
    from_num   = os.getenv("COOLSMS_FROM_NUMBER","").strip()
    if not all([api_key, api_secret, from_num]):
        raise ValueError("COOLSMS_API_KEY, COOLSMS_API_SECRET, COOLSMS_FROM_NUMBER가 .env에 없습니다.")
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    salt = _uuid.uuid4().hex
    sig  = hmac.new(api_secret.encode(), (date+salt).encode(), hashlib.sha256).hexdigest()
    headers = {
        "Authorization": f"HMAC-SHA256 apiKey={api_key}, date={date}, salt={salt}, signature={sig}",
        "Content-Type": "application/json;charset=UTF-8",
    }
    body = {"message": {
        "to":   to_number.replace("-","").replace(" ",""),
        "from": from_num.replace("-","").replace(" ",""),
        "text": message,
    }}
    resp = requests.post("https://api.coolsms.co.kr/messages/v4/send", headers=headers, json=body)
    if resp.status_code != 200:
        raise Exception(f"SMS 전송 실패 (HTTP {resp.status_code}): {resp.text}")


# ── UI ────────────────────────────────────────────────────────────────────────

col_doc, col_photo = st.columns(2)

with col_doc:
    st.subheader("📄 문서 업로드")
    doc_files = st.file_uploader(
        "건축물대장 · 등기부등본 (PDF, HWP, DOCX, 이미지)",
        type=["pdf","jpg","jpeg","png","bmp","tiff","tif","webp","docx","hwp","hwpx"],
        accept_multiple_files=True,
        key="docs",
    )
    if doc_files:
        st.caption(f"✅ {len(doc_files)}개: " + ", ".join(f.name for f in doc_files))

with col_photo:
    st.subheader("📷 매물 사진 업로드 (선택)")
    photo_files = st.file_uploader(
        "없으면 AI가 자동으로 이미지를 생성합니다",
        type=["jpg","jpeg","png","bmp","webp","tiff"],
        accept_multiple_files=True,
        key="photos",
    )
    if photo_files:
        st.caption(f"✅ {len(photo_files)}개: " + ", ".join(f.name for f in photo_files))
    else:
        st.caption("📌 사진 미업로드 시 Gemini + ChatGPT 두 이미지를 동시 생성 후 비교·선택 가능")

additional_info = st.text_area(
    "✏️ 추가 강조 사항 (선택)",
    height=70,
    placeholder="예: 역세권, 주차 가능, 즉시 입주 가능, 리모델링 완료 등",
)

if st.button("🚀 콘텐츠 자동 생성 (블로그 SEO + 카드뉴스 포함)", type="primary", use_container_width=True):
    if not doc_files:
        st.warning("📄 문서 파일을 먼저 업로드해주세요.")
    else:
        all_texts, doc_images = [], []
        with st.spinner("📖 문서 분석 중..."):
            for f in doc_files:
                try:
                    t, i = process_doc_file(f)
                    all_texts.extend(t); doc_images.extend(i)
                except Exception as e:
                    st.error(f"❌ {f.name}: {e}")

        # 매물 사진 처리
        prop_images_b64 = []
        prop_img_bytes  = None
        if photo_files:
            for f in photo_files:
                data = f.read()
                ext  = f.name.lower().rsplit(".",1)[-1]
                mime = MIME_MAP.get(ext, "image/jpeg")
                prop_images_b64.append((base64.b64encode(data).decode(), mime))
            prop_img_bytes = photo_files[0].getvalue()
            st.session_state.pop("img_gemini",  None)
            st.session_state.pop("img_chatgpt", None)

        if not all_texts and not doc_images:
            st.error("❌ 분석 가능한 내용이 없습니다."); st.stop()

        # 콘텐츠 생성
        with st.spinner("🤖 AI가 6가지 콘텐츠 생성 중... (20~50초)"):
            try:
                sections = call_openai(all_texts, doc_images, prop_images_b64, additional_info)
                st.session_state["sections"] = sections
                key_info = parse_key_info_dict(sections.get("핵심정보",""))
                st.session_state["key_info"] = key_info
            except Exception as e:
                st.error(f"❌ 콘텐츠 생성 오류: {e}"); st.stop()

        # AI 이미지 생성 (사진 없을 때 — 두 AI 동시 생성)
        if not prop_img_bytes:
            with st.spinner("🎨 Gemini + ChatGPT 이미지 동시 생성 중... (20~40초)"):
                with ThreadPoolExecutor(max_workers=2) as ex:
                    f_g = ex.submit(generate_ai_image_gemini,  st.session_state["key_info"])
                    f_c = ex.submit(generate_ai_image_chatgpt, st.session_state["key_info"])
                    img_g = f_g.result()
                    img_c = f_c.result()
            st.session_state["img_gemini"]  = img_g
            st.session_state["img_chatgpt"] = img_c
            prop_img_bytes = img_g or img_c  # Gemini 기본 선택

        st.session_state["prop_img_bytes"] = prop_img_bytes

        # 카드뉴스 생성 (기본 이미지로)
        with st.spinner("🃏 카드뉴스 5장 제작 중..."):
            cards = create_card_news(sections, st.session_state["key_info"], prop_img_bytes)
            st.session_state["cards"] = cards

        st.success("✅ 모든 콘텐츠 생성 완료!")


# ── 결과 탭 ───────────────────────────────────────────────────────────────────

if "sections" in st.session_state:
    sec      = st.session_state["sections"]
    cards    = st.session_state.get("cards", [])
    prop_img = st.session_state.get("prop_img_bytes")

    st.markdown("---")

    # ── AI 이미지 비교 · 선택 (AI 생성 시에만 표시) ──────────────────────────
    img_gemini  = st.session_state.get("img_gemini")
    img_chatgpt = st.session_state.get("img_chatgpt")

    if img_gemini or img_chatgpt:
        st.subheader("🖼️ AI 생성 이미지 비교 · 선택")
        c_g, c_c = st.columns(2)
        with c_g:
            if img_gemini:
                st.image(img_gemini, use_container_width=True)
                st.caption("✅ Gemini 3.1")
            else:
                st.warning("Gemini 이미지 생성 실패")
        with c_c:
            if img_chatgpt:
                st.image(img_chatgpt, use_container_width=True)
                st.caption("✅ ChatGPT (gpt-image-1)")
            else:
                st.warning("ChatGPT 이미지 생성 실패")

        choices = []
        if img_gemini:  choices.append("Gemini 3.1")
        if img_chatgpt: choices.append("ChatGPT (gpt-image-1)")

        img_choice = st.radio(
            "카드뉴스 · 전체 다운로드에 사용할 이미지",
            choices, horizontal=True, key="img_choice",
        )
        if st.button("✅ 선택 이미지 적용 (카드뉴스 재생성)", use_container_width=True):
            chosen = img_gemini if "Gemini" in img_choice else img_chatgpt
            st.session_state["prop_img_bytes"] = chosen
            with st.spinner("🃏 카드뉴스 재생성 중..."):
                new_cards = create_card_news(
                    st.session_state["sections"],
                    st.session_state["key_info"],
                    chosen,
                )
                st.session_state["cards"] = new_cards
            st.rerun()

        st.markdown("---")

    # ── 전체 다운로드 버튼 ────────────────────────────────────────────────────
    dl_col1, dl_col2 = st.columns(2)
    with dl_col1:
        master_zip = create_master_zip(sec, cards, prop_img)
        st.download_button(
            label="📦 전체 콘텐츠 한번에 다운로드 (ZIP)",
            data=master_zip,
            file_name="부동산_콘텐츠_패키지.zip",
            mime="application/zip",
            use_container_width=True,
            type="primary",
        )
    with dl_col2:
        if prop_img:
            st.download_button(
                label="🖼️ 매물 사진 별도 다운로드",
                data=prop_img,
                file_name="매물_사진.jpg",
                mime="image/jpeg",
                use_container_width=True,
            )

    st.caption("📦 ZIP 안에 텍스트 6종 + 카드뉴스 5장 + 매물 사진이 모두 포함됩니다.")
    st.markdown("---")

    tab_blog, tab_insta, tab_thread, tab_shorts, tab_intro, tab_card, tab_info = st.tabs([
        "📝 블로그(SEO)", "📸 인스타그램", "🔵 쓰레드",
        "🎬 쇼츠 컨셉",  "📄 매물 소개서", "🃏 카드뉴스", "ℹ️ 핵심 정보",
    ])

    def content_tab(tab, key, title, fname, show_social=True):
        with tab:
            # ── 통합 미리보기 (사진 + 텍스트) ────────────────────────────────
            if prop_img:
                st.image(prop_img, use_container_width=True)
            st.markdown(sec[key])
            st.markdown("---")

            # ── 다운로드 + 소셜 버튼 ─────────────────────────────────────────
            html_data = make_html(title, sec[key], prop_img).encode("utf-8")

            b1, b2, b3, b4, b5 = st.columns(5)
            with b1:
                st.download_button(
                    "📥 HTML 저장",
                    data=html_data, file_name=fname,
                    mime="text/html", key=f"dl_html_{key}",
                    use_container_width=True,
                )
            with b2:
                safe = sec[key].replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
                components.html(f"""
                <button onclick="navigator.clipboard.writeText(`{safe}`)
                    .then(()=>{{this.innerText='✅ 복사됨!';
                    setTimeout(()=>this.innerText='📋 복사',2000)}})
                    .catch(()=>alert('복사 실패'))"
                    style="width:100%;padding:8px;background:#4caf50;color:#fff;
                    border:none;border-radius:6px;cursor:pointer;font-size:14px">
                    📋 복사
                </button>""", height=42)
            if show_social:
                with b3:
                    st.link_button("📸 인스타그램", "https://www.instagram.com/",
                                   use_container_width=True)
                with b4:
                    st.link_button("👤 페이스북", "https://www.facebook.com/",
                                   use_container_width=True)
                with b5:
                    threads_url = "https://www.threads.net/intent/post?text=" + \
                                  urllib.parse.quote(sec[key][:500])
                    st.link_button("🔵 쓰레드", threads_url,
                                   use_container_width=True)
            st.caption("📸 인스타·페이스북: 📋 복사 후 해당 앱에서 붙여넣기 | 🔵 쓰레드: 텍스트 자동 입력됨")

    content_tab(tab_blog,   "네이버블로그", "네이버 블로그 매물 광고",  "블로그(SEO).html")
    content_tab(tab_thread, "쓰레드",       "쓰레드 매물 소개",         "쓰레드.html")
    content_tab(tab_shorts, "쇼츠컨셉",     "유튜브 쇼츠 기획안",       "쇼츠_컨셉.html", show_social=False)
    content_tab(tab_intro,  "매물소개서",   "매물 소개서",              "매물_소개서.html")

    # ── 인스타그램 탭 (계정 연동 업로드 포함) ─────────────────────────────────
    with tab_insta:
        if prop_img:
            st.image(prop_img, use_container_width=True)
        st.markdown(sec["인스타그램"])
        st.markdown("---")

        b1, b2, b3, b4 = st.columns(4)
        html_ig = make_html("인스타그램 매물 소개", sec["인스타그램"], prop_img).encode("utf-8")
        with b1:
            st.download_button("📥 HTML 저장", data=html_ig, file_name="인스타그램.html",
                               mime="text/html", key="dl_html_insta", use_container_width=True)
        with b2:
            safe_ig = sec["인스타그램"].replace("\\","\\\\").replace("`","\\`").replace("$","\\$")
            components.html(f"""<button onclick="navigator.clipboard.writeText(`{safe_ig}`)
                .then(()=>{{this.innerText='✅ 복사됨!';setTimeout(()=>this.innerText='📋 복사',2000)}})
                .catch(()=>alert('복사 실패'))"
                style="width:100%;padding:8px;background:#4caf50;color:#fff;
                border:none;border-radius:6px;cursor:pointer;font-size:14px">📋 복사</button>""", height=42)
        with b3:
            st.link_button("📸 인스타그램 앱", "https://www.instagram.com/", use_container_width=True)
        with b4:
            threads_url_ig = "https://www.threads.net/intent/post?text=" + \
                             urllib.parse.quote(sec["인스타그램"][:500])
            st.link_button("🔵 쓰레드", threads_url_ig, use_container_width=True)

        st.markdown("---")
        st.subheader("📲 Instagram 비즈니스 계정으로 바로 업로드")

        ig_token = os.getenv("INSTAGRAM_ACCESS_TOKEN","").strip()
        ig_id    = os.getenv("INSTAGRAM_USER_ID","").strip()
        imgbb_k  = os.getenv("IMGBB_API_KEY","").strip()

        if not all([ig_token, ig_id, imgbb_k]):
            st.warning("⚠️ .env에 INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_USER_ID, IMGBB_API_KEY를 입력해야 합니다.")
            with st.expander("📖 설정 방법 보기"):
                st.markdown("""
**1단계 — imgbb API 키** (이미지 임시 호스팅)
- [imgbb.com](https://imgbb.com) 무료 가입 → 우측 상단 프로필 → **API** → API Key 복사
- `.env`에 `IMGBB_API_KEY=발급받은키` 입력

**2단계 — Meta 앱 생성**
- [developers.facebook.com](https://developers.facebook.com) → **내 앱 → 앱 만들기**
- 앱 유형: **비즈니스** 선택
- Instagram Graph API 제품 추가

**3단계 — 액세스 토큰 발급**
- [Graph API Explorer](https://developers.facebook.com/tools/explorer/) 접속
- 앱 선택 → **Generate Access Token** 클릭
- 권한 추가: `instagram_basic`, `instagram_content_publish`, `pages_read_engagement`
- **Generate Access Token** → 토큰 복사

**4단계 — 장기 토큰 교환** (60일 유효)
```
GET https://graph.facebook.com/oauth/access_token
  ?grant_type=fb_exchange_token
  &client_id={앱ID}
  &client_secret={앱시크릿}
  &fb_exchange_token={단기토큰}
```

**5단계 — Instagram User ID 확인**
```
GET https://graph.facebook.com/v21.0/me/accounts?access_token={토큰}
```
→ 반환된 계정의 `instagram_business_account.id` 값

**6단계 — .env 입력**
```
INSTAGRAM_ACCESS_TOKEN=장기토큰
INSTAGRAM_USER_ID=숫자로된ID
IMGBB_API_KEY=imgbb키
```
""")
        else:
            if prop_img is None:
                st.info("📷 매물 사진을 먼저 생성하거나 업로드해야 합니다.")
            else:
                caption_text = sec["인스타그램"]
                if st.button("📲 Instagram에 지금 바로 업로드", type="primary",
                             use_container_width=True, key="btn_ig_post"):
                    with st.spinner("📤 Instagram에 업로드 중..."):
                        try:
                            post_id = post_to_instagram(prop_img, caption_text)
                            st.success(f"✅ Instagram 업로드 완료! (게시물 ID: {post_id})")
                            st.balloons()
                        except Exception as e:
                            st.error(f"❌ 업로드 실패: {e}")

    with tab_card:
        st.subheader("🃏 카드뉴스 (1080×1080)")
        if prop_img:
            st.image(prop_img, use_container_width=True)
        if cards:
            names = ["커버", "주요정보", "건물특징", "투자포인트", "문의안내"]
            cols  = st.columns(5)
            for col, card, name in zip(cols, cards, names):
                buf = io.BytesIO()
                card.save(buf, format="PNG")
                col.image(buf.getvalue(), caption=name, use_container_width=True)

            zip_data = cards_to_zip(cards)
            st.download_button(
                label="📥 카드뉴스 전체 다운로드 (ZIP)",
                data=zip_data,
                file_name="카드뉴스.zip",
                mime="application/zip",
                use_container_width=True,
            )
            st.caption("개별 카드 다운로드:")
            dl_cols = st.columns(5)
            for col, card, name in zip(dl_cols, cards, names):
                buf = io.BytesIO()
                card.save(buf, format="PNG")
                col.download_button(
                    label=name,
                    data=buf.getvalue(),
                    file_name=f"카드뉴스_{name}.png",
                    mime="image/png",
                    key=f"dl_card_{name}",
                )
        else:
            st.info("콘텐츠를 먼저 생성하면 카드뉴스가 여기에 표시됩니다.")

    with tab_info:
        st.subheader("ℹ️ 핵심 정보 요약")
        st.markdown(sec["핵심정보"])

    # ── 전송 섹션 ─────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📤 전송하기")
    c_info, c_email, c_sms, c_kakao = st.columns([2,1,1,1])

    with c_info:
        st.markdown("#### 👤 수신자 정보")
        r_name  = st.text_input("이름",     placeholder="홍길동",         key="r_name")
        r_email = st.text_input("이메일",   placeholder="example@email.com", key="r_email")
        r_phone = st.text_input("전화번호", placeholder="010-1234-5678",  key="r_phone")

    with c_email:
        st.markdown("#### 📧 이메일")
        st.caption("매물 소개서 전송")
        if st.button("이메일 전송", use_container_width=True, key="btn_email"):
            if not r_email:
                st.warning("이메일 주소를 입력하세요.")
            else:
                try:
                    send_email(r_email, f"[매물 소개] {r_name}님께" if r_name else "[매물 소개]", sec["매물소개서"])
                    st.success("✅ 전송 완료!")
                except ValueError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"❌ {e}")

    with c_sms:
        st.markdown("#### 📱 문자(SMS)")
        st.caption("쓰레드 내용 전송")
        if st.button("문자 전송", use_container_width=True, key="btn_sms"):
            if not r_phone:
                st.warning("전화번호를 입력하세요.")
            else:
                try:
                    send_sms(r_phone, sec["쓰레드"][:200])
                    st.success("✅ 전송 완료!")
                except ValueError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"❌ {e}")

    with c_kakao:
        st.markdown("#### 💬 카카오톡")
        st.caption("복사 후 붙여넣기")
        st.text_area("", value=sec["쓰레드"], height=160,
                     key="kakao_copy", label_visibility="collapsed")
        st.caption("Ctrl+A → Ctrl+C → 카카오톡")

st.markdown("---")
st.caption("⚠️ 개인정보 보호: 소유자 성명 등 민감한 개인정보는 자동으로 제외됩니다.")
