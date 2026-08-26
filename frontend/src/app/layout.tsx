import type { Metadata } from "next";
import { headers } from "next/headers";
import "./globals.css";
import { NavBar } from "@/components/NavBar";

export const metadata: Metadata = {
  title: "Project11 — 三阶段写作工坊",
  description: "三阶段 LLM 流水线：DeepSeek 草稿 → Qwen 精修 → Claude 评估",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const nonce = headers().get("x-nonce");
  return (
    <html lang="zh-CN">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,500;0,600;0,700;1,400;1,500&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,500;0,8..60,600;1,8..60,400;1,8..60,500&family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
        <script
          nonce={nonce ?? undefined}
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem("project11:theme");if(t&&t!=="dark")document.documentElement.dataset.theme=t}catch(e){}`,
          }}
        />
      </head>
      <body>
        <div className="flex flex-col h-screen overflow-hidden" style={{ background: "var(--bg)" }}>
          <NavBar />
          <div className="flex-1 min-h-0 overflow-hidden">{children}</div>
        </div>
      </body>
    </html>
  );
}
