import type { ToneKey, NodeMeta } from './tokens';

export interface NodeLibraryProps {
  /** Se o drawer está aberto */
  open: boolean;
  /**
   * Callback de mudança de estado.
   * - `onClose(true)` → feche
   * - `onClose(false)` → abra (chamado pelo FAB)
   *
   * Exemplo: `onClose={(shouldClose) => setOpen(!shouldClose)}`
   */
  onClose: (shouldClose: boolean) => void;
  /** Chamado quando usuário adiciona um node via botão + ou duplo-clique */
  onAdd: (type: string) => void;
  /** Opcional: notificado quando drag começa */
  onDragStart?: (type: string) => void;
}

export type { ToneKey, NodeMeta };
