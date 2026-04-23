# Node Library — Drawer de seleção de nodes

Biblioteca lateral elegante para selecionar/arrastar tipos de node para um canvas de workflow (React Flow, Reaflow, etc).

![preview](./preview.png)

## ✨ Features

- **Drawer lateral animado** (380px, slide-in esquerda)
- **Busca** por nome, tipo, descrição ou tags
- **Filtros por grupo** (chips clicáveis com contadores)
- **Grid/List toggle** — cards com preview ou linhas compactas
- **Mini-preview** do body de cada node dentro do card (fiel ao real)
- **Drag-and-drop** via `dataTransfer` (`application/x-node-type`)
- **Duplo-clique** ou botão **+** adiciona ao canvas
- **Hover glow** da tone do grupo em cada card
- **Empty state** + footer com affordances de uso
- **Atalho `L`** para toggle, `Esc` para fechar
- **FAB** aparece quando drawer está fechado

## 📦 Arquivos

```
handoff-library/
├── README.md                        ← este arquivo
├── src/
│   ├── NodeLibrary.jsx              ← componente principal (drawer + cards + busca)
│   ├── node-library.css             ← estilos isolados, prefixo .lib-*
│   ├── tokens.ts                    ← paleta de tones + metadados dos 26 nodes
│   └── types.ts                     ← tipos TypeScript
└── examples/
    └── integration.tsx              ← exemplo de integração com React Flow
```

## 🔌 Integração (5 minutos)

### 1. Instale dependências

```bash
npm install lucide-react
```

> Nota: o componente assume `React` disponível como global ou importado. Ajuste os imports no topo de `NodeLibrary.jsx` para seu stack.

### 2. Importe o CSS

```tsx
import './node-library.css';
```

### 3. Use o componente

```tsx
import { NodeLibrary } from './NodeLibrary';

function WorkflowCanvas() {
  const [libOpen, setLibOpen] = useState(true);

  return (
    <>
      <NodeLibrary
        open={libOpen}
        onClose={(shouldClose) => setLibOpen(!shouldClose)}
        onAdd={(type) => {
          // adicione o node ao seu state
          myCanvas.addNode({ type, position: { x: 200, y: 200 } });
        }}
      />

      <ReactFlow
        onDragOver={(e) => {
          if (e.dataTransfer.types.includes('application/x-node-type')) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
          }
        }}
        onDrop={(e) => {
          const type = e.dataTransfer.getData('application/x-node-type');
          if (!type) return;
          const pos = rfInstance.screenToFlowPosition({ x: e.clientX, y: e.clientY });
          myCanvas.addNodeAt(type, pos);
        }}
        // ...
      />
    </>
  );
}
```

## 🎨 Customização

### Trocar os node types

Edite `NODE_META` em `tokens.ts` (ou no topo de `NodeLibrary.jsx`):

```ts
export const NODE_META = [
  {
    type: 'cron',                    // ID único
    group: 'purple',                 // uma das 6 tones
    label: 'Cron',                   // título visível
    icon: 'Clock',                   // nome do ícone lucide-react
    desc: 'Dispara em um agendamento cron',
    tags: ['agendamento', 'tempo', 'trigger'],  // para busca
  },
  // ...
];
```

### Trocar os mini-previews

Abra `NodeLibrary.jsx`, vai no componente `MiniBody` e adicione um `case` pro seu novo `type`:

```tsx
case 'meuNode':
  return <div className="mono text-[9px] text-slate-700">meu preview</div>;
```

### Mudar as tones

Edite `TONES` em `tokens.ts`. Cada tone define:
- `name` — rótulo do grupo ("Triggers", "Actions"...)
- `dot` — cor sólida (#hex)
- `tile` — fundo suave do ícone
- `tileRing` — ring do ícone (rgba)
- `ink` — cor do ícone dentro do tile
- `glow` — shadow de hover (rgba)
- `head` — classe Tailwind do título do grupo

## 🧩 API

### Props

| prop        | tipo                            | default | descrição                                      |
|-------------|---------------------------------|---------|------------------------------------------------|
| `open`      | `boolean`                       | —       | Se o drawer está aberto                        |
| `onClose`   | `(shouldClose: boolean) => void`| —       | `true` fecha, `false` abre                     |
| `onAdd`     | `(type: string) => void`        | —       | Chamado quando usuário adiciona via +/duplo-clique |
| `onDragStart`| `(type: string) => void`        | —       | Opcional, avisa quando drag começa             |

### Drag-and-drop

O drawer configura:
```
dataTransfer.effectAllowed = 'copy'
dataTransfer.setData('application/x-node-type', meta.type)
```

Seu canvas deve ler esse tipo no `onDrop`.

## 🎯 Dependências

- **React 18+**
- **lucide-react** (ícones)
- **Tailwind CSS** (algumas classes utilitárias no markup — ou inline-style equivalente)

> Se não usa Tailwind, as classes utilizadas são poucas (`flex`, `items-center`, `gap-2`, `min-w-0`, `truncate`, `flex-1`, `mono`, tamanhos de texto). Fácil de substituir por CSS puro ou seu sistema.

## ⚠️ Regras

1. **IDs dos nodes (`type`) são contratos** — usados no `dataTransfer` e no `onAdd`. Mantenha consistência com seu backend.
2. **Ícones vêm de `lucide-react`** — os nomes em `NODE_META.icon` devem existir na lib.
3. **Prefixo CSS `.lib-*`** não colide com seu app. Mantenha.
4. **`z-index` do drawer: 45**, FAB: 40. Ajuste se tiver modais acima.

## 📐 Anatomia visual

```
┌─────────────────────────────────────┐
│ ▢ Node Library     [grid|list] [X] │  ← header
│   26 of 26 types                    │
├─────────────────────────────────────┤
│ 🔍 Buscar por nome, tipo, tag…     │  ← search
├─────────────────────────────────────┤
│ •Triggers 5  •Actions 5  •Logic 6… │  ← group chips
├─────────────────────────────────────┤
│                                     │
│ ● TRIGGERS  5 ─────────────────     │  ← group header
│                                     │
│ ┌───────────┐ ┌───────────┐         │
│ │ ◢ [i] Cron│ │ ◢ [i] Hook│  ← card │
│ │           │ │           │         │
│ │ 0 */4 * * │ │ POST /api │         │
│ └───────────┘ └───────────┘         │
│                                     │
│ (scrollable)                        │
├─────────────────────────────────────┤
│ ✋ Arraste · Duplo-clique · [L]    │  ← footer
└─────────────────────────────────────┘
```
