/**
 * Tones (cores por grupo) e metadados dos 26 nodes.
 * Fonte da verdade — se adicionar um novo node, adicione aqui.
 */

export type ToneKey = 'purple' | 'emerald' | 'orange' | 'cyan' | 'slate' | 'pink';

export interface ToneDef {
  /** Nome do grupo (visível ao usuário) */
  name: string;
  /** Cor sólida principal (hex) */
  dot: string;
  /** Fundo suave do tile do ícone (hex) */
  tile: string;
  /** Ring do tile (rgba) */
  tileRing: string;
  /** Cor do ícone dentro do tile (hex) */
  ink: string;
  /** Sombra/glow de hover (rgba) */
  glow: string;
  /** Classe Tailwind para o header do grupo (text-{color}-700) */
  head: string;
}

export const TONES: Record<ToneKey, ToneDef> = {
  purple: {
    name: 'Triggers',
    dot: '#9333ea',
    tile: '#f5f3ff',
    tileRing: 'rgba(147,51,234,0.20)',
    ink: '#7c3aed',
    glow: 'rgba(147, 51, 234, 0.22)',
    head: 'text-purple-700',
  },
  emerald: {
    name: 'Actions',
    dot: '#059669',
    tile: '#ecfdf5',
    tileRing: 'rgba(5,150,105,0.20)',
    ink: '#047857',
    glow: 'rgba(5, 150, 105, 0.22)',
    head: 'text-emerald-700',
  },
  orange: {
    name: 'Logic',
    dot: '#ea580c',
    tile: '#fff7ed',
    tileRing: 'rgba(234,88,12,0.20)',
    ink: '#c2410c',
    glow: 'rgba(234, 88, 12, 0.22)',
    head: 'text-orange-700',
  },
  cyan: {
    name: 'Transformation',
    dot: '#0891b2',
    tile: '#ecfeff',
    tileRing: 'rgba(8,145,178,0.20)',
    ink: '#0e7490',
    glow: 'rgba(8, 145, 178, 0.22)',
    head: 'text-cyan-700',
  },
  slate: {
    name: 'Storage',
    dot: '#475569',
    tile: '#f8fafc',
    tileRing: 'rgba(71,85,105,0.20)',
    ink: '#334155',
    glow: 'rgba(71, 85, 105, 0.22)',
    head: 'text-slate-700',
  },
  pink: {
    name: 'AI',
    dot: '#db2777',
    tile: '#fdf2f8',
    tileRing: 'rgba(219,39,119,0.20)',
    ink: '#be185d',
    glow: 'rgba(219, 39, 119, 0.22)',
    head: 'text-pink-700',
  },
};

export interface NodeMeta {
  type: string;
  group: ToneKey;
  label: string;
  icon: string;            // nome do ícone em lucide-react
  desc: string;            // 1 linha
  tags?: string[];         // para busca
}

export const NODE_META: NodeMeta[] = [
  { type:'cron',       group:'purple',  label:'Cron',         icon:'Clock',             desc:'Dispara em um agendamento cron',           tags:['agendamento','tempo','trigger'] },
  { type:'webhook',    group:'purple',  label:'Webhook',      icon:'Webhook',           desc:'Recebe uma requisição HTTP externa',        tags:['http','api','trigger'] },
  { type:'manual',     group:'purple',  label:'Manual',       icon:'MousePointerClick', desc:'Dispara manualmente com um clique',         tags:['teste','debug'] },
  { type:'subTrigger', group:'purple',  label:'Sub-WF Start', icon:'CornerDownRight',   desc:'Recebe execução de um workflow pai',        tags:['sub-workflow','interno'] },
  { type:'queue',      group:'purple',  label:'Queue',        icon:'Radio',             desc:'Consome mensagens de RabbitMQ / Kafka',     tags:['fila','evento','async'] },

  { type:'http',       group:'emerald', label:'HTTP',         icon:'Globe',             desc:'Faz uma chamada REST externa',              tags:['api','rest','get','post'] },
  { type:'sql',        group:'emerald', label:'SQL',          icon:'Database',          desc:'Executa uma query SQL',                      tags:['postgres','mysql','banco'] },
  { type:'email',      group:'emerald', label:'Email',        icon:'Mail',              desc:'Envia um email transacional',                tags:['smtp','notificação'] },
  { type:'execSub',    group:'emerald', label:'Execute WF',   icon:'PlaySquare',        desc:'Executa um sub-workflow (sync/async)',      tags:['reuso','modular'] },
  { type:'nosql',      group:'emerald', label:'NoSQL',        icon:'FileCog',           desc:'Operação em Mongo / DynamoDB',               tags:['document','nosql'] },

  { type:'if',         group:'orange',  label:'If',           icon:'Split',             desc:'Bifurca o fluxo por condição (true/false)', tags:['condição','branch'] },
  { type:'switch',     group:'orange',  label:'Switch',       icon:'Route',             desc:'Roteia entre múltiplas saídas',             tags:['roteamento','múltiplo'] },
  { type:'loop',       group:'orange',  label:'Loop',         icon:'Repeat',            desc:'Itera sobre uma coleção',                    tags:['for','map','iteração'] },
  { type:'merge',      group:'orange',  label:'Merge',        icon:'Combine',           desc:'Sincroniza duas entradas em uma saída',     tags:['join','sync'] },
  { type:'errorCatch', group:'orange',  label:'Error Catch',  icon:'ShieldAlert',       desc:'Intercepta erros de outro node',             tags:['erro','catch','exception'] },
  { type:'wait',       group:'orange',  label:'Wait',         icon:'Timer',             desc:'Pausa o fluxo por um período',               tags:['delay','sleep'] },

  { type:'mapper',     group:'cyan',    label:'Mapper',       icon:'Shuffle',           desc:'Remapeia campos entre objetos',              tags:['transform','de/para'] },
  { type:'code',       group:'cyan',    label:'Code',         icon:'Code2',             desc:'Executa JavaScript inline',                  tags:['script','custom'] },
  { type:'datetime',   group:'cyan',    label:'Date/Time',    icon:'CalendarClock',     desc:'Formata / converte datas',                   tags:['data','formato'] },
  { type:'conv',       group:'cyan',    label:'Converter',    icon:'FileType2',         desc:'CSV ↔ JSON ↔ XML',                           tags:['conversão','parse'] },

  { type:'state',      group:'slate',   label:'State',        icon:'BookMarked',        desc:'Lê/grava estado global',                     tags:['global','variável'] },
  { type:'file',       group:'slate',   label:'File',         icon:'FileText',          desc:'Lê/grava arquivo em disco',                  tags:['disk','storage'] },

  { type:'llm',        group:'pink',    label:'LLM',          icon:'Sparkles',          desc:'Chamada a um modelo (GPT-4, Claude…)',      tags:['ai','prompt','gpt'] },
  { type:'mem',        group:'pink',    label:'Memory',       icon:'Brain',             desc:'Buffer de memória conversacional',           tags:['chat','contexto'] },
  { type:'vector',     group:'pink',    label:'Vector',       icon:'Search',            desc:'Busca vetorial (Pinecone, Weaviate)',       tags:['rag','embedding'] },
  { type:'agent',      group:'pink',    label:'Agent',        icon:'Bot',               desc:'Agente LLM com ferramentas',                 tags:['tools','react','autônomo'] },
];
