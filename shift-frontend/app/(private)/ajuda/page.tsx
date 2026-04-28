import { redirect } from "next/navigation"
import { listArticles } from "@/lib/docs/loader"

export default async function AjudaIndex() {
  const articles = await listArticles()
  // Sem artigos: mensagem; com: redireciona pro primeiro.
  if (articles.length === 0) {
    return (
      <div className="text-sm text-muted-foreground">
        Nenhum artigo disponível.
      </div>
    )
  }
  redirect(`/ajuda/${articles[0].slug}`)
}
