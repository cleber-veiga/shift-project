# Migration Guide — Integrando os Nodes ao Seu Projeto

Roteiro para migrar do HTML standalone para um projeto React + React Flow em produção.

---

## 🌊 Estratégia recomendada: 3 ondas

**Não adapte os 26 nodes de uma vez.** Vai por ondas pra ter checkpoints e evitar retrabalho.

### Onda 1 — Base (30min)

Só trazer `CanvasNode`, `TONES`, `PortHandle` e o CSS pro teu stack. Zero mudança visual.

**Prompt sugerido no Claude Code:**

```
Contexto: Estou integrando um design system de nodes pro meu workflow canvas.
Os arquivos em `handoff/src/` são a referência visual definitiva.

Tarefa: Adapte `handoff/src/CanvasNode.jsx` + `workflow-nodes.css` + `tokens.ts`
pro meu stack:
- Converta JSX → TSX com tipagem do React Flow (NodeProps<T>)
- Ajuste imports pros aliases do meu projeto (ex: @/components/workflow)
- Mantenha EXATAMENTE o visual — não "melhore" nada
- Use o meu setup de Tailwind (já configurado em tailwind.config.ts)

Output: `src/components/workflow/CanvasNode.tsx` + `styles/workflow-nodes.css`.
```

**Checkpoint:** renderize UM node hardcoded (ex: `<CanvasNode tone="purple" title="Test" />`) num canvas React Flow vazio. Se aparecer certinho, avança.

---

### Onda 2 — 3 nodes piloto (1h)

Adapte 3 nodes que cobrem os casos críticos:
- **`CronNode`** — caso simples (sem entrada, 1 saída, body curto)
- **`IfNode`** — múltiplas saídas rotuladas ("True" / "False")
- **`LLMNode`** — body rico (badge + pílulas + aspas)

**Prompt:**

```
Adapte os 3 nodes de referência abaixo pro meu projeto, seguindo o mesmo padrão
que usamos pra CanvasNode na Onda 1:

1. CronNode — `handoff/src/nodes.jsx` (procurar por "CronNode")
2. IfNode — mesmo arquivo
3. LLMNode — mesmo arquivo

Regras:
- Cada um vira `src/components/workflow/nodes/{Nome}.tsx`
- Importe dados do meu backend: my types em `src/workflow/node-data.ts`
- NÃO invente tones, NÃO troque ícones do lucide, NÃO mude a anatomia
- Preserve IDs dos handles: true, false, item, done, in1, in2, etc.
- Body com `nodrag` (obrigatório pra interatividade funcionar)

Vou revisar os 3 antes de adaptar os outros 23.
```

**Checkpoint:** conecte esses 3 nodes com edges e confirme que:
- Drag funciona (header é draggable, body não)
- Handles conectam (dot → dot)
- Labels das portas aparecem ("True"/"False" no IfNode)
- Status chip anima (`running` deve pulsar)

---

### Onda 3 — Resto em lote (1h)

Agora que você validou o padrão, solta a manada:

**Prompt:**

```
Ok, os 3 nodes piloto foram revisados e estão certos. Adapte os outros 23 nodes
de `handoff/src/nodes.jsx` seguindo EXATAMENTE o mesmo padrão:

[ lista: WebhookNode, ManualNode, SubWorkflowTriggerNode, EventQueueTriggerNode,
  HttpRequestNode, SqlDatabaseNode, EmailSenderNode, ExecuteSubWorkflowNode,
  NoSQLDatabaseNode, SwitchNode, LoopNode, MergeNode, ErrorCatchNode, WaitNode,
  MapperNode, CodeNode, DateTimeNode, DataConverterNode, GlobalStateNode,
  FileStorageNode, ChatMemoryNode, VectorStoreNode, AgentNode ]

No final, registre TODOS em `src/components/workflow/nodeTypes.ts`:

export const nodeTypes = {
  cron: CronNode,
  webhook: WebhookNode,
  // ... etc
};

E exporte `NODE_META` com { label, group, icon, description } pra eu montar
o command palette.
```

---

## 🧱 Mapping dos tipos (JS → TS)

O `handoff/src/types.ts` já tem as interfaces prontas. Principais tipos:

```ts
export type Tone = 'purple' | 'emerald' | 'orange' | 'cyan' | 'slate' | 'pink';

export type NodeStatus = 'idle' | 'running' | 'ok' | 'error' | 'disabled';

export interface PortDef {
  id: string;      // ID semântico: 'true', 'false', 'item', 'done', 'in1'
  label?: string;  // Texto inline ao lado do handle
}

export interface CanvasNodeProps {
  tone: Tone;
  icon: LucideIcon;
  title: string;
  subtitle?: string;
  status?: NodeStatus;
  inputs?: PortDef[];
  outputs?: PortDef[];
  disabled?: boolean;
  onRename?: (newName: string) => void;
  // ... ações do menu: onRun, onDuplicate, onRemove, etc.
  children?: React.ReactNode;  // body glanceable
}
```

Cada node concreto define seu próprio `NodeData` e passa pro `<CanvasNode>`:

```ts
// Exemplo: CronNode
export interface CronNodeData {
  expression: string;  // "0 */4 * * *"
  timezone: string;    // "America/Sao_Paulo"
  nextRun?: string;    // "00:42:11"
}

export function CronNode({ data, id }: NodeProps<CronNodeData>) {
  // ...
}
```

---

## 🚨 Armadilhas comuns

Quando for rodar no Claude Code, **anexe essas avisos no prompt pra ele não cair**:

1. ❌ "Vou trocar lucide-react por heroicons" → **NÃO.** Mantém lucide.
2. ❌ "Vou simplificar PortHandle pra uma div" → **NÃO.** Quebra React Flow.
3. ❌ "Vou usar CSS-in-JS" → **NÃO.** É Tailwind + CSS puro.
4. ❌ "Vou renomear os IDs dos handles pra ficar em inglês/português consistente" → **NÃO.** IDs são contratos de dados.
5. ❌ "O body não precisa do `nodrag`" → **SIM, precisa.** Sem ele, clicks no body viram drag do node.
6. ❌ "Vou mover as tones pra theme do Tailwind" → Pode, desde que os nomes (`purple`, `emerald`, etc.) permaneçam.

---

## ✅ Checklist final

Antes de considerar integrado:

- [ ] Um workflow de exemplo com 5+ nodes conectados renderiza
- [ ] Drag + pan + zoom funcionam
- [ ] Handles conectam entre nodes (validar com IfNode → 2 edges saindo)
- [ ] Status chip anima (`running` pulsa, `error` fica vermelho)
- [ ] Menu de ações (•••) abre e funciona (Rename, Run, Duplicate, Remove)
- [ ] Rename inline (duplo-clique no título) funciona
- [ ] Minimap colorido por tone
- [ ] Command palette (⌘K) busca entre os 26 tipos

---

## 🔧 Troubleshooting

**"Os handles não conectam"**
→ Verifique `type="source"` ou `type="target"` no `<Handle>` (PortHandle já faz isso corretamente).

**"O body é draggable quando não deveria"**
→ Falta `className="nodrag"` no wrapper do body.

**"As cores das tones não aparecem"**
→ Tailwind não está varrendo seus arquivos. Adicione ao `content` do `tailwind.config.ts`:
```ts
content: ['./src/components/workflow/**/*.{ts,tsx}'],
```
Ou use os CSS variables de `workflow-nodes.css` direto.

**"O glow/shadow no hover não aparece"**
→ `workflow-nodes.css` não foi importado. Adicione no teu entry point.
