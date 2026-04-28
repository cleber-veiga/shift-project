import Link from "next/link"
import { listArticles } from "@/lib/docs/loader"
import { BookOpen } from "lucide-react"

export const metadata = {
  title: "Ajuda — Shift",
}

export default async function AjudaLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const articles = await listArticles()

  return (
    <div className="flex h-full min-h-0 flex-1 overflow-hidden">
      {/* Sidebar */}
      <aside className="flex w-64 shrink-0 flex-col gap-1 border-r border-border bg-card/40 p-4">
        <div className="mb-4 flex items-center gap-2">
          <BookOpen className="size-4 text-muted-foreground" />
          <h1 className="text-sm font-semibold">Ajuda</h1>
        </div>
        <nav className="flex flex-col gap-0.5">
          {articles.map((a) => (
            <Link
              key={a.slug}
              href={`/ajuda/${a.slug}`}
              className="rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground aria-[current=page]:bg-accent aria-[current=page]:text-foreground"
            >
              {a.title}
            </Link>
          ))}
        </nav>
        {articles.length === 0 && (
          <p className="text-xs text-muted-foreground">
            Nenhum artigo disponível.
          </p>
        )}
      </aside>

      {/* Content */}
      <main className="flex-1 overflow-y-auto px-8 py-8">
        <div className="mx-auto max-w-3xl">{children}</div>
      </main>
    </div>
  )
}
