/**
 * Loader server-side de artigos de documentacao.
 *
 * Le markdown de ``content/docs/*.md``, parsea o frontmatter (YAML simples
 * com title + order) e expoe a lista pra a sidebar e o conteudo cru pra
 * renderizacao via react-markdown.
 *
 * Roda em server components (Next App Router) — usa fs/promises sem
 * problema. NAO usa em client components.
 */

import { promises as fs } from "fs"
import path from "path"

const DOCS_DIR = path.join(process.cwd(), "content", "docs")

export type DocMeta = {
  slug: string
  title: string
  order: number
}

export type DocArticle = DocMeta & {
  body: string
}

function parseFrontmatter(raw: string): { meta: Record<string, string>; body: string } {
  // Frontmatter no formato:
  //   ---
  //   key: value
  //   ---
  //   conteudo...
  // Sem dependencia externa — parser minimo, suficiente pro nosso uso.
  const match = raw.match(/^---\n([\s\S]*?)\n---\n([\s\S]*)$/)
  if (!match) return { meta: {}, body: raw }

  const meta: Record<string, string> = {}
  for (const line of match[1].split("\n")) {
    const idx = line.indexOf(":")
    if (idx < 0) continue
    const k = line.slice(0, idx).trim()
    const v = line.slice(idx + 1).trim()
    if (k) meta[k] = v
  }
  return { meta, body: match[2] }
}

export async function listArticles(): Promise<DocMeta[]> {
  let files: string[]
  try {
    files = await fs.readdir(DOCS_DIR)
  } catch {
    return []
  }
  const articles: DocMeta[] = []
  for (const f of files) {
    if (!f.endsWith(".md")) continue
    const slug = f.replace(/\.md$/, "")
    const raw = await fs.readFile(path.join(DOCS_DIR, f), "utf-8")
    const { meta } = parseFrontmatter(raw)
    articles.push({
      slug,
      title: meta.title || slug,
      order: parseInt(meta.order ?? "999", 10),
    })
  }
  articles.sort((a, b) => a.order - b.order)
  return articles
}

export async function getArticle(slug: string): Promise<DocArticle | null> {
  // Sanitiza slug — bloqueia path traversal (../, /, etc).
  if (!/^[a-z0-9-]+$/i.test(slug)) return null
  try {
    const raw = await fs.readFile(path.join(DOCS_DIR, `${slug}.md`), "utf-8")
    const { meta, body } = parseFrontmatter(raw)
    return {
      slug,
      title: meta.title || slug,
      order: parseInt(meta.order ?? "999", 10),
      body,
    }
  } catch {
    return null
  }
}
