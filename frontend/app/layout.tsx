import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "ATS Talent Intelligence",
  description: "Explainable AI ranking for recruiting",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
