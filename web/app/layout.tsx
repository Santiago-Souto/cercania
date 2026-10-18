import type { Metadata, Viewport } from "next";
import { Atkinson_Hyperlegible, Bricolage_Grotesque } from "next/font/google";
import "./globals.css";
import { cn } from "@/lib/utils";
import { Toaster } from "@/components/ui/sonner";

// Fonts from docs/design/DESIGN.md: Atkinson Hyperlegible for body, Bricolage Grotesque for headings.
const atkinson = Atkinson_Hyperlegible({
  variable: "--font-sans",
  weight: ["400", "700"],
  subsets: ["latin"],
});

const bricolage = Bricolage_Grotesque({
  variable: "--font-display",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "CercanIA",
  description: "El traspaso de turno que no se pierde.",
  applicationName: "CercanIA",
  // Installed from the home screen on iPhone: open full screen, keep the status bar readable.
  appleWebApp: { capable: true, title: "CercanIA", statusBarStyle: "default" },
  // Phone numbers in reports are data, not links.
  formatDetection: { telephone: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0e5a55",
  // Lets env(safe-area-inset-*) work, so bottom bars clear the iPhone home indicator.
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className={cn(atkinson.variable, bricolage.variable, "font-sans")}>
      <body className="text-base antialiased">
        {children}
        <Toaster position="top-center" />
      </body>
    </html>
  );
}
