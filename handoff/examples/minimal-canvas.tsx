/**
 * Exemplo mínimo — um canvas React Flow com 3 nodes do design system.
 * Cole isso numa página limpa pra validar que tudo carregou certo.
 */

import { useCallback, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  applyNodeChanges,
  applyEdgeChanges,
  type Node,
  type Edge,
  type Connection,
  type NodeChange,
  type EdgeChange,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import '../src/workflow-nodes.css';

import { NODE_TYPES } from '../src/nodes'; // ou import { nodeTypes } from '@/components/workflow/nodeTypes'

const initialNodes: Node[] = [
  {
    id: 'cron-1',
    type: 'cron',
    position: { x: 80, y: 120 },
    data: {
      name: 'Every 4h',
      expression: '0 */4 * * *',
      timezone: 'America/Sao_Paulo',
      nextRun: '00:42:11',
      status: 'ok',
    },
  },
  {
    id: 'if-1',
    type: 'if',
    position: { x: 420, y: 120 },
    data: {
      name: 'High-value check',
      condition: '{{order.total}} > 1000',
      status: 'idle',
    },
  },
  {
    id: 'email-1',
    type: 'emailSender',
    position: { x: 760, y: 40 },
    data: {
      name: 'VIP notification',
      to: '{{user.email}}',
      subject: 'Pedido premium confirmado',
      status: 'idle',
    },
  },
  {
    id: 'email-2',
    type: 'emailSender',
    position: { x: 760, y: 220 },
    data: {
      name: 'Standard confirmation',
      to: '{{user.email}}',
      subject: 'Pedido confirmado',
      status: 'idle',
    },
  },
];

const initialEdges: Edge[] = [
  { id: 'e1', source: 'cron-1', target: 'if-1', sourceHandle: 'out', targetHandle: 'in' },
  { id: 'e2', source: 'if-1', target: 'email-1', sourceHandle: 'true', targetHandle: 'in' },
  { id: 'e3', source: 'if-1', target: 'email-2', sourceHandle: 'false', targetHandle: 'in' },
];

export function MinimalCanvas() {
  const [nodes, setNodes] = useState<Node[]>(initialNodes);
  const [edges, setEdges] = useState<Edge[]>(initialEdges);

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => setNodes((nds) => applyNodeChanges(changes, nds)),
    [],
  );
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => setEdges((eds) => applyEdgeChanges(changes, eds)),
    [],
  );
  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge(connection, eds)),
    [],
  );

  return (
    <div style={{ width: '100vw', height: '100vh' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={NODE_TYPES}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView
      >
        <Background gap={16} size={1.5} color="#cbd5e1" />
        <Controls />
        <MiniMap pannable zoomable />
      </ReactFlow>
    </div>
  );
}
