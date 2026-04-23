# Workflow Canvas — Node Design System (Handoff)

Um sistema visual para 26 tipos de nós de workflow, desenhado para React Flow (`@xyflow/react`).

> **Objetivo:** glanceability — bater o olho e entender o que o nó faz, sem abrir configurações.

---

## 📦 Conteúdo do pacote

```
handoff/
├── README.md                    ← este arquivo
├── MIGRATION.md                 ← guia passo-a-passo para adaptar ao seu projeto
├── src/
│   ├── CanvasNode.jsx           ← Componente base + TONES + PortHandle (O MOTOR VISUAL)
│   ├── nodes.jsx                ← 26 node types + NODE_TYPES registry + NODE_META
│   ├── workflow-nodes.css       ← Tokens CSS, glass, handles, body-surface
│   ├── tokens.ts                ← Paleta e dimensões isoladas (fonte da verdade)
│   └── types.ts                 ← Tipos TypeScript para NodeData, Tone, PortDef
└── examples/
    └── minimal-canvas.tsx       ← Canvas React Flow mínimo usando os nodes
```

---

## 🧩 Anatomia do Node

Todo node usa o mesmo **contrato visual** via `<CanvasNode>`:

```
┌──────────────────────────────┐
│ ◢ (corner accent da cor)     │
│ [ICON] Título          ⦿ok•• │  ← header (drag handle)
│        subtítulo opcional     │
├──────────────────────────────┤  ← divider gradient
│                              │
│   [ body glanceable ]        │  ← conteúdo visual, NÃO formulário
│                              │
└──────────────────────────────┘
   •← entrada              saída →•
```

- **Container:** glass (`bg-white/95` + backdrop-blur), `rounded-2xl`, shadow com glow da tone no hover.
- **Header:** ícone em tile colorido, título em negrito, subtítulo opcional, status chip + menu à direita.
- **Body:** fundo `body-surface` (acinzentado inset), com `nodrag` pra permitir interação.
- **Handles:** `<PortHandle>` wrapeia o `<Handle>` do React Flow. Suporta label inline (ex: "True"/"False").

---

## 🎨 As 6 Tones (grupos)

Cada node pertence a um grupo com uma tone de cor:

| Grupo           | Tone      | Uso                                              |
| --------------- | --------- | ------------------------------------------------ |
| Triggers        | `purple`  | Cron, Webhook, Manual, SubWorkflow, EventQueue   |
| Actions         | `emerald` | HTTP, SQL, Email, ExecuteSubWorkflow, NoSQL      |
| Logic           | `orange`  | If, Switch, Loop, Merge, ErrorCatch, Wait        |
| Transformation  | `cyan`    | Mapper, Code, DateTime, DataConverter            |
| Storage         | `slate`   | GlobalState, FileStorage                         |
| AI              | `pink`    | LLM, ChatMemory, VectorStore, Agent              |

> **Regra:** não inventar tones novas. Se um node novo aparecer, encaixe em um dos 6 grupos existentes.

Os valores exatos estão em `src/tokens.ts` (e espelhados em `src/workflow-nodes.css` via CSS variables).

---

## 📝 Como adicionar um novo node

```tsx
// src/nodes/MyCustomNode.tsx
import { CanvasNode, PortHandle } from '../CanvasNode';
import { Zap } from 'lucide-react';

export function MyCustomNode({ data }: NodeProps<MyCustomNodeData>) {
  return (
    <CanvasNode
      tone="emerald"              // ← um dos 6
      icon={Zap}
      title={data.name}
      subtitle="ação customizada"
      status={data.status}        // 'idle' | 'running' | 'ok' | 'error'
      inputs={[{ id: 'in' }]}     // portas de entrada
      outputs={[{ id: 'out' }]}   // portas de saída
    >
      {/* Body glanceable — 1 a 3 linhas */}
      <div className="text-[12px] text-slate-600">
        <span className="font-mono">{data.expression}</span>
      </div>
    </CanvasNode>
  );
}
```

Depois registre em `nodeTypes` do React Flow:

```tsx
const nodeTypes = {
  ...NODE_TYPES,             // os 26 prontos
  myCustom: MyCustomNode,    // o seu
};
```

---

## ⚠️ Regras que quebram se ignoradas

1. **`nodrag` no body** — senão inputs/botões dentro do body não funcionam (o React Flow intercepta como drag).
2. **IDs dos handles são contratos** — `true`, `false`, `item`, `done`, `in1`, `in2`, etc. Os edges do backend referenciam esses IDs.
3. **Handles são `<Handle>` nativos** — não divs com CSS. `PortHandle` já wrapa — não "simplifique".
4. **Lucide obrigatório** — todos os ícones vêm de `lucide-react`. Misturar libs quebra o visual.
5. **Tailwind é a linguagem de estilo** — `workflow-nodes.css` tem só o que Tailwind não cobre (keyframes, pseudo-elements complexos).

---

## 🔗 Dependências

```json
{
  "@xyflow/react": "^12.3.5",
  "react": "^18",
  "react-dom": "^18",
  "lucide-react": "^0.454.0",
  "tailwindcss": "^3.4"
}
```

---

Veja `MIGRATION.md` para o passo-a-passo de integração no seu projeto.
