import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import { ThemeProvider } from "@/components/theme-provider"
import { UiPreferencesProvider } from "@/lib/context/ui-preferences-context"
import { ToastProvider } from "@/lib/context/toast-context"
import "./globals.css"

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
})

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
})

export const metadata: Metadata = {
  title: {
    default: "Shift Frontend",
    template: "%s | Shift Frontend",
  },
  description: "Fluxos iniciais de autenticacao da plataforma Shift.",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} min-h-screen`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <UiPreferencesProvider>
            <ToastProvider>{children}</ToastProvider>
          </UiPreferencesProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
