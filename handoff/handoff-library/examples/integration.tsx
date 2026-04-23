/**
 * Exemplo completo de integração com React Flow.
 *
 * Abra esse arquivo pra ver como conectar:
 * - Abrir/fechar drawer
 * - Adicionar node via onAdd
 * - Receber drop do drawer no canvas
 * - Atalho de teclado (L)
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ReactFlow, ReactFlowProvider, Background, Controls,
  useNodesState, useEdgesState, useReactFlow, addEdge,
  type Node, type Edge, type Connection,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { NodeLibrary } from '../src/NodeLibrary';
import { NODE_META } from '../src/tokens';
import '../src/node-library.css';

// Seus nodeTypes customizados. Troque pelos seus.
import { nodeTypes } from './nodeTypes';

function WorkflowShell() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [libraryOpen, setLibraryOpen] = useState(true);
  const [dropping, setDropping] = useState(false);
  const rfInstance = useReactFlow();

  const onConnect = useCallback(
    (c: Connection) => setEdges((eds) => addEdge(c, eds)),
    [setEdges],
  );

  // ---------- keyboard: L = toggle library, Esc = close ----------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName?.toLowerCase();
      const typing = tag === 'input' || tag === 'textarea' || (e.target as HTMLElement)?.isContentEditable;
      if (!typing && (e.key === 'l' || e.key === 'L')) {
        e.preventDefault();
        setLibraryOpen((o) => !o);
      }
      if (e.key === 'Escape') setLibraryOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ---------- adicionar node ao canvas ----------
  const addNode = useCallback(
    (type: string, position?: { x: number; y: number }) => {
      const meta = NODE_META.find((m) => m.type === type);
      const pos = position || { x: 200 + Math.random() * 200, y: 200 + Math.random() * 200 };
      const newId = `${type}-${Date.now().toString(36)}`;
      setNodes((ns) => [
        ...ns,
        {
          id: newId,
          type,
          position: pos,
          data: { title: meta?.label || type },
          selected: true,
        },
      ]);
    },
    [setNodes],
  );

  // ---------- drag-and-drop do drawer ----------
  const onDragOver = useCallback((e: React.DragEvent) => {
    if (e.dataTransfer.types.includes('application/x-node-type')) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      setDropping(true);
    }
  }, []);

  const onDragLeave = useCallback(() => setDropping(false), []);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      setDropping(false);
      const type = e.dataTransfer.getData('application/x-node-type');
      if (!type) return;
      e.preventDefault();
      const pos = rfInstance.screenToFlowPosition({ x: e.clientX, y: e.clientY });
      addNode(type, pos);
    },
    [rfInstance, addNode],
  );

  return (
    <>
      <NodeLibrary
        open={libraryOpen}
        onClose={(shouldClose) => setLibraryOpen(!shouldClose)}
        onAdd={(type) => addNode(type)}
      />

      <div
        className={dropping ? 'canvas-dropping' : ''}
        onDragOver={onDragOver}
        onDragLeave={onDragLeave}
        onDrop={onDrop}
        style={{ width: '100vw', height: '100vh' }}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          fitView
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </>
  );
}

export function App() {
  return (
    <ReactFlowProvider>
      <WorkflowShell />
    </ReactFlowProvider>
  );
}
