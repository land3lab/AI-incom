import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: '부동산 AI 콘텐츠 작성기',
  description: '건축물대장·등기부등본 → 블로그·인스타·쓰레드·카드뉴스 자동 생성',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <body className="bg-gray-50 min-h-screen">{children}</body>
    </html>
  );
}
