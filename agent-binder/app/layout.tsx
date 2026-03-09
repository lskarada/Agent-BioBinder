import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Agent Binder | CXCL12 Target",
  description: "Autonomous multi-agent peptide binder design for CXCL12",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="bg-gray-950 text-gray-100" suppressHydrationWarning>
        {children}
      </body>
    </html>
  );
}
