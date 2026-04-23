import type { LucideIcon } from 'lucide-react';
import type { NodeProps } from '@xyflow/react';
import type { Tone } from './tokens';

export type { Tone } from './tokens';

export type NodeStatus = 'idle' | 'running' | 'ok' | 'error' | 'disabled';

/**
 * Definição de uma porta de conexão (handle).
 * O `id` é o contrato referenciado por edges — preservar nomes exatos
 * entre backend e frontend ("true", "false", "item", "done", "in1", "in2").
 */
export interface PortDef {
  id: string;
  label?: string;
}

export type NodeGroup =
  | 'Triggers'
  | 'Actions'
  | 'Logic'
  | 'Transformation'
  | 'Storage'
  | 'AI';

/** Props do componente base CanvasNode — esqueleto visual compartilhado */
export interface CanvasNodeProps {
  id?: string;
  tone: Tone;
  icon: LucideIcon;
  title: string;
  subtitle?: string;
  status?: NodeStatus;
  inputs?: PortDef[];
  outputs?: PortDef[];
  disabled?: boolean;
  /** Callbacks acionados pelo menu •••  */
  onRename?: (newName: string) => void;
  onRun?: () => void;
  onDuplicate?: () => void;
  onRemove?: () => void;
  onToggleDisabled?: () => void;
  /** Body glanceable — 1 a 3 linhas mostrando o estado/config do node */
  children?: React.ReactNode;
}

/** Metadados de cada tipo de node — usados no command palette e na sidebar */
export interface NodeMeta {
  type: string;            // 'cron', 'webhook', 'if', ...
  label: string;           // 'Cron', 'Webhook', 'If' (título visível)
  group: NodeGroup;
  tone: Tone;
  icon: LucideIcon;
  description: string;     // 1 linha explicando o que faz
  /** Template inicial de data quando o node é arrastado pro canvas */
  defaultData: Record<string, unknown>;
}

// ---------- Types específicos por node type ----------
// Estes refletem o `data` de cada React Flow node.

export interface CronNodeData {
  expression: string;    // "0 */4 * * *"
  timezone: string;      // "America/Sao_Paulo"
  nextRun?: string;      // "00:42:11" (computado)
  status?: NodeStatus;
  name?: string;
}

export interface WebhookNodeData {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  path: string;          // "/api/orders"
  status?: NodeStatus;
  name?: string;
}

export interface ManualNodeData {
  status?: NodeStatus;
  name?: string;
}

export interface SubWorkflowTriggerNodeData {
  parentName: string;
  inputs: { key: string; type: string }[];
  status?: NodeStatus;
  name?: string;
}

export interface EventQueueTriggerNodeData {
  broker: 'rabbitmq' | 'kafka' | 'sqs';
  topic: string;
  status?: NodeStatus;
  name?: string;
}

export interface HttpRequestNodeData {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  url: string;
  status?: NodeStatus;
  name?: string;
}

export interface SqlDatabaseNodeData {
  query: string;
  status?: NodeStatus;
  name?: string;
}

export interface EmailSenderNodeData {
  to: string;            // "{{user.email}}"
  subject: string;
  status?: NodeStatus;
  name?: string;
}

export interface ExecuteSubWorkflowNodeData {
  target: string;        // nome do workflow
  sync: boolean;
  status?: NodeStatus;
  name?: string;
}

export interface NoSQLDatabaseNodeData {
  operation: string;     // "db.logs.insertOne(...)"
  status?: NodeStatus;
  name?: string;
}

export interface IfNodeData {
  condition: string;     // "{{valor}} > 1000"
  status?: NodeStatus;
  name?: string;
}

export interface SwitchNodeData {
  variable: string;      // "{{tipo}}"
  routes: string[];      // ["Rota 1", "Rota 2", "Default"]
  status?: NodeStatus;
  name?: string;
}

export interface LoopNodeData {
  array: string;         // "{{items}}"
  status?: NodeStatus;
  name?: string;
}

export interface MergeNodeData {
  strategy: 'wait-all' | 'first-wins';
  status?: NodeStatus;
  name?: string;
}

export interface ErrorCatchNodeData {
  message?: string;
  status?: NodeStatus;
  name?: string;
}

export interface WaitNodeData {
  durationMs: number;
  progress?: number;     // 0..1
  status?: NodeStatus;
  name?: string;
}

export interface MapperNodeData {
  mappings: { from: string; to: string }[];
  status?: NodeStatus;
  name?: string;
}

export interface CodeNodeData {
  language: 'javascript' | 'python';
  code: string;
  status?: NodeStatus;
  name?: string;
}

export interface DateTimeNodeData {
  from: string;          // "ISO8601"
  to: string;            // "DD/MM/YYYY"
  status?: NodeStatus;
  name?: string;
}

export interface DataConverterNodeData {
  from: 'CSV' | 'JSON' | 'XML' | 'YAML';
  to: 'CSV' | 'JSON' | 'XML' | 'YAML';
  status?: NodeStatus;
  name?: string;
}

export interface GlobalStateNodeData {
  key: string;           // "ultimo_id"
  value: string;         // "{{id}}"
  status?: NodeStatus;
  name?: string;
}

export interface FileStorageNodeData {
  path: string;
  operation: 'read' | 'write' | 'delete';
  status?: NodeStatus;
  name?: string;
}

export interface LLMNodeData {
  model: string;         // "gpt-4", "claude-sonnet-4"
  prompt: string;        // truncado no body
  status?: NodeStatus;
  name?: string;
}

export interface ChatMemoryNodeData {
  bufferSize: number;
  status?: NodeStatus;
  name?: string;
}

export interface VectorStoreNodeData {
  provider: 'pinecone' | 'weaviate' | 'qdrant' | 'chroma';
  query: string;
  status?: NodeStatus;
  name?: string;
}

export interface AgentNodeData {
  tools: string[];       // ["SQL", "WEB", "EMAIL"]
  status?: NodeStatus;
  name?: string;
}

// Helper type para NodeProps tipado
export type TypedNodeProps<T> = NodeProps<{ data: T } & T>;
