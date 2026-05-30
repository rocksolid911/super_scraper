import './globals.css';
import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: 'Super Scraper',
  description: 'Scrape anything from any website — natural language or visual selection.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
