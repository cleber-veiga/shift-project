import { InputModelDataPage } from "@/components/dashboard/input-model-data-page"

interface PageProps {
  params: Promise<{ modelId: string }>
}

export default async function Page({ params }: PageProps) {
  const { modelId } = await params
  return <InputModelDataPage modelId={modelId} />
}
