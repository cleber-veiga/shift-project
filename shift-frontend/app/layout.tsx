import type { Metadata } from "next"
import { Inter_Tight, JetBrains_Mono } from "next/font/google"
import { ThemeProvider } from "@/components/theme-provider"
import { UiPreferencesProvider } from "@/lib/context/ui-preferences-context"
import { ToastProvider } from "@/lib/context/toast-context"
import "./globals.css"

const interTight = Inter_Tight({
  variable: "--font-inter-tight",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
})

const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
  display: "swap",
})

export const metadata: Metadata = {
  title: {
    default: "Shift",
    template: "%s | Shift",
  },
  description: "Plataforma de workflows de ETL — orquestre extração, transformação e carga entre sistemas.",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <body
        className={`${interTight.variable} ${jetbrainsMono.variable} min-h-screen`}
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
