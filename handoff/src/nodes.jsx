/* 26 node type components — each wraps CanvasNode with its specific body.
   They take (props) from React Flow: { id, data, selected }. */

function n(tone, icon, defaultTitle, subtitle, inputs, outputs, width=260) {
  return { tone, icon, defaultTitle, subtitle, inputs, outputs, width };
}

/* 1. TRIGGERS */
function CronNode(p) { return (
  <CanvasNode {...p} {...n('purple','Clock','Schedule','cron · America/Sao_Paulo',[],[{id:'out'}])}>
    <div className="flex items-center justify-between">
      <div className="mono text-[13px] text-slate-800 tracking-wider">0 */4 * * *</div>
      <Badge tone="purple">every 4h</Badge>
    </div>
    <div className="mt-2 text-[10px] text-slate-500">Next run in 00:42:11</div>
  </CanvasNode>
); }

function WebhookNode(p) { return (
  <CanvasNode {...p} {...n('purple','Webhook','Webhook','public endpoint',[],[{id:'out'}])}>
    <div className="flex items-center gap-2">
      <Badge tone="emerald" solid>POST</Badge>
      <div className="mono text-[11px] text-slate-700 truncate">/hooks/checkout/confirm</div>
    </div>
    <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-500">
      <Icon name="Lock" size={11} /> Bearer auth · 1.2k hits/24h
    </div>
  </CanvasNode>
); }

function ManualNode(p) { return (
  <CanvasNode {...p} {...n('purple','MousePointerClick','Manual Trigger','run on demand',[],[{id:'out'}])}>
    <div className="flex items-center gap-2">
      <div className="w-8 h-8 rounded-lg bg-white border border-slate-200 flex items-center justify-center">
        <Icon name="Mouse" size={16} className="text-slate-500" />
      </div>
      <div>
        <div className="text-[11px] text-slate-700 font-medium">Awaiting click</div>
        <div className="text-[10px] text-slate-500">Triggered by operator</div>
      </div>
    </div>
  </CanvasNode>
); }

function SubWorkflowTriggerNode(p) { return (
  <CanvasNode {...p} {...n('purple','GitBranch','Sub-workflow Start','called by parent',[],[{id:'out'}])}>
    <div className="text-[10.5px] text-slate-500 mb-1.5">Awaiting parent flow</div>
    <div className="space-y-1">
      <KV k="in:" v="order_id : string" />
      <KV k="in:" v="user     : object" />
      <KV k="in:" v="retry    : number" />
    </div>
  </CanvasNode>
); }

function EventQueueTriggerNode(p) { return (
  <CanvasNode {...p} {...n('purple','Radio','Queue Listener','consumer group: etl-01',[],[{id:'out'}])}>
    <div className="flex items-center gap-2 mb-1.5">
      <Badge tone="orange" solid>RabbitMQ</Badge>
      <div className="mono text-[11px] text-slate-700 truncate">topic · orders.created</div>
    </div>
    <div className="flex items-center gap-2 text-[10px] text-slate-500">
      <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 pulse-ring" />
      42 msg/s · lag 0
    </div>
  </CanvasNode>
); }

/* 2. ACTIONS */
function HttpRequestNode(p) { return (
  <CanvasNode {...p} {...n('emerald','Globe','HTTP Request','fetch · 3s timeout',[{id:'in'}],[{id:'out'}])}>
    <div className="flex items-center gap-2">
      <Badge tone="blue" solid>GET</Badge>
      <div className="mono text-[11px] text-slate-700 truncate">api.stripe.com/v1/customers</div>
    </div>
    <div className="mt-2 flex items-center gap-3 text-[10px] text-slate-500">
      <span className="flex items-center gap-1"><Icon name="CheckCircle2" size={11} className="text-emerald-500" /> 200 OK</span>
      <span>124 ms</span><span>2.1 KB</span>
    </div>
  </CanvasNode>
); }

function SqlDatabaseNode(p) { return (
  <CanvasNode {...p} {...n('emerald','Database','SQL Query','postgres · analytics',[{id:'in'}],[{id:'out'}])}>
    <div className="code-dark">
      <div><span className="tok-key">SELECT</span> id, email, total</div>
      <div><span className="tok-key">FROM</span> <span className="tok-var">orders</span></div>
      <div><span className="tok-key">WHERE</span> status = <span className="tok-str">'paid'</span></div>
      <div className="truncate"><span className="tok-key">AND</span> created_at &gt; <span className="tok-num">{'{{'}since{'}}'}</span></div>
    </div>
  </CanvasNode>
); }

function EmailSenderNode(p) { return (
  <CanvasNode {...p} {...n('emerald','Mail','Send Email','sendgrid · transactional',[{id:'in'}],[{id:'out'}])}>
    <div className="space-y-1">
      <KV k="to:"   v={<span>{'{{'}<span className="text-emerald-700">user.email</span>{'}}'}</span>} />
      <KV k="subj:" v="Your order is confirmed ✓" />
      <KV k="tmpl:" v="order-receipt.v3" />
    </div>
  </CanvasNode>
); }

function ExecuteSubWorkflowNode(p) { return (
  <CanvasNode {...p} {...n('emerald','GitPullRequestArrow','Execute Workflow','nested flow',[{id:'in'}],[{id:'out'}])}>
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-1.5">
        <Icon name="Workflow" size={12} className="text-emerald-700" />
        <span className="text-[12px] font-medium text-slate-800">Fraud Check v2</span>
      </div>
      <Badge tone="emerald">Sync</Badge>
    </div>
    <div className="mt-2 text-[10px] text-slate-500">12 nodes · avg 340ms</div>
  </CanvasNode>
); }

function NoSQLDatabaseNode(p) { return (
  <CanvasNode {...p} {...n('emerald','Layers','NoSQL Operation','mongodb · logs-cluster',[{id:'in'}],[{id:'out'}])}>
    <div className="code-dark">
      <div><span className="tok-var">db</span><span className="tok-op">.</span><span className="tok-var">logs</span><span className="tok-op">.</span><span className="tok-fn">insertOne</span>(</div>
      <div className="pl-3">{'{'} event: <span className="tok-str">'order_paid'</span>, ts {'}'}</div>
      <div>)</div>
    </div>
  </CanvasNode>
); }

/* 3. LOGIC */
function IfNode(p) { return (
  <CanvasNode {...p} {...n('orange','Split','If / Condition','branching',[{id:'in'}],[{id:'true',label:'True'},{id:'false',label:'False'}], 280)}>
    <div className="rounded-lg bg-white border border-slate-200 px-2.5 py-2">
      <div className="text-[10px] text-slate-400 mono mb-1">condition</div>
      <div className="mono text-[12px] text-slate-800">
        {'{{'}<span className="text-orange-700">order.total</span>{'}}'}
        <span className="text-slate-400 mx-1.5">&gt;</span>
        <span className="text-amber-700">1000</span>
      </div>
    </div>
  </CanvasNode>
); }

function SwitchNode(p) { return (
  <CanvasNode {...p} {...n('orange','Shuffle','Switch','multi-branch',[{id:'in'}],[{id:'r1',label:'Route 1'},{id:'r2',label:'Route 2'},{id:'def',label:'Default'}], 290)}>
    <div className="text-[10px] text-slate-400 mono mb-1">evaluate</div>
    <div className="mono text-[12px] text-slate-800 mb-2">
      {'{{'}<span className="text-orange-700">user.plan</span>{'}}'}
    </div>
    <div className="flex gap-1 flex-wrap">
      <Badge tone="orange">"pro"</Badge>
      <Badge tone="orange">"team"</Badge>
      <Badge tone="slate">else</Badge>
    </div>
  </CanvasNode>
); }

function LoopNode(p) { return (
  <CanvasNode {...p} {...n('orange','Repeat','Loop / For Each','batch size: 25',[{id:'in'}],[{id:'item',label:'Item'},{id:'done',label:'Done'}], 280)}>
    <div className="text-[10px] text-slate-400 mono mb-1">iterate</div>
    <div className="mono text-[12px] text-slate-800 mb-1.5">
      {'{{'}<span className="text-orange-700">items</span>{'}}'}
      <span className="text-slate-400 ml-1">[ 142 ]</span>
    </div>
    <div className="w-full h-1.5 rounded-full bg-slate-200 overflow-hidden">
      <div className="h-full rounded-full bg-orange-500" style={{ width: '43%' }} />
    </div>
    <div className="mt-1 flex justify-between text-[10px] text-slate-500 mono">
      <span>61 / 142</span><span>ETA 00:22</span>
    </div>
  </CanvasNode>
); }

function MergeNode(p) { return (
  <CanvasNode {...p} {...n('orange','Merge','Merge Streams','wait for both',[{id:'in1',label:'In 1'},{id:'in2',label:'In 2'}],[{id:'out'}], 280)}>
    <div className="flex items-center justify-between text-[11px]">
      <div className="flex items-center gap-1.5">
        <Icon name="GitMerge" size={12} className="text-orange-700" />
        <span className="text-slate-700">Mode</span>
      </div>
      <Badge tone="orange">combine</Badge>
    </div>
    <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-500">
      <Icon name="Hourglass" size={11} /> waiting on input 2
    </div>
  </CanvasNode>
); }

function ErrorCatchNode(p) { return (
  <CanvasNode {...p} {...n('orange','ShieldAlert','Error Catch','global handler',[],[{id:'out'}], 270)}>
    <div className="rounded-lg bg-rose-50 border border-rose-200 px-2.5 py-2">
      <div className="flex items-start gap-2">
        <Icon name="AlertTriangle" size={13} className="text-rose-600 mt-0.5" />
        <div>
          <div className="text-[11px] font-semibold text-rose-700">Intercepts uncaught errors</div>
          <div className="mono text-[10.5px] text-rose-600 mt-0.5 truncate">TimeoutError · 502 · ValidationErr</div>
        </div>
      </div>
    </div>
  </CanvasNode>
); }

function WaitNode(p) { return (
  <CanvasNode {...p} {...n('orange','Timer','Wait / Delay','pause execution',[{id:'in'}],[{id:'out'}], 270)}>
    <div className="flex items-center justify-between mb-1.5">
      <div className="mono text-[14px] text-slate-800 font-semibold">15 min</div>
      <div className="text-[10px] text-slate-500">remaining 06:12</div>
    </div>
    <div className="relative w-full h-1.5 rounded-full bg-slate-200 overflow-hidden shimmer">
      <div className="h-full rounded-full bg-orange-500" style={{ width: '58%' }} />
    </div>
  </CanvasNode>
); }

/* 4. TRANSFORMATION */
function MapperNode(p) { return (
  <CanvasNode {...p} {...n('cyan','ArrowRightLeft','Field Mapper','rename · reshape',[{id:'in'}],[{id:'out'}])}>
    <div className="mono text-[11px] space-y-0.5">
      <div className="flex items-center gap-1.5"><span className="text-slate-500">name</span><Icon name="ArrowRight" size={11} className="text-cyan-600" /><span className="text-slate-800">{'{{'}n{'}}'} {'{{'}s{'}}'}</span></div>
      <div className="flex items-center gap-1.5"><span className="text-slate-500">email</span><Icon name="ArrowRight" size={11} className="text-cyan-600" /><span className="text-slate-800">contact</span></div>
      <div className="flex items-center gap-1.5"><span className="text-slate-500">amt_cents</span><Icon name="ArrowRight" size={11} className="text-cyan-600" /><span className="text-slate-800">amount / 100</span></div>
    </div>
  </CanvasNode>
); }

function CodeNode(p) { return (
  <CanvasNode {...p} {...n('cyan','Code2','Run Code','javascript · v20',[{id:'in'}],[{id:'out'}])}>
    <div className="code-dark">
      <div><span className="tok-key">const</span> <span className="tok-var">sum</span> <span className="tok-op">=</span> <span className="tok-var">items</span></div>
      <div className="pl-2">.<span className="tok-fn">map</span>(i {'=>'} i.price)</div>
      <div className="pl-2">.<span className="tok-fn">reduce</span>((a,b) {'=>'} a+b, <span className="tok-num">0</span>);</div>
    </div>
  </CanvasNode>
); }

function DateTimeNode(p) { return (
  <CanvasNode {...p} {...n('cyan','CalendarClock','Date / Time','format · timezone',[{id:'in'}],[{id:'out'}])}>
    <div className="flex items-center gap-2">
      <Badge tone="cyan">ISO 8601</Badge>
      <Icon name="ArrowRight" size={12} className="text-slate-400" />
      <Badge tone="cyan">DD/MM/YYYY</Badge>
    </div>
    <div className="mt-2 mono text-[10.5px] text-slate-500 truncate">2026-04-23T14:21Z → 23/04/2026</div>
  </CanvasNode>
); }

function DataConverterNode(p) { return (
  <CanvasNode {...p} {...n('cyan','FileJson','Data Converter','parse · serialize',[{id:'in'}],[{id:'out'}])}>
    <div className="flex items-center gap-2">
      <Badge tone="amber">CSV</Badge>
      <Icon name="ArrowRight" size={12} className="text-slate-400" />
      <Badge tone="cyan">JSON</Badge>
    </div>
    <div className="mt-2 flex items-center gap-3 text-[10px] text-slate-500">
      <span>header row: yes</span><span>delim: ","</span>
    </div>
  </CanvasNode>
); }

/* 5. STORAGE */
function GlobalStateNode(p) { return (
  <CanvasNode {...p} {...n('slate','Boxes','Global State','shared · key-value',[{id:'in'}],[{id:'out'}])}>
    <div className="mono text-[11px] text-slate-800">
      <span className="text-slate-500">ultimo_id</span>
      <span className="mx-1.5 text-slate-400">=</span>
      {'{{'}<span className="text-slate-700">order.id</span>{'}}'}
    </div>
    <div className="mt-1.5 flex items-center gap-1.5 text-[10px] text-slate-500">
      <Icon name="RefreshCw" size={11} /> updated 2s ago
    </div>
  </CanvasNode>
); }

function FileStorageNode(p) { return (
  <CanvasNode {...p} {...n('slate','FolderOpen','File Storage','read · S3 bucket',[{id:'in'}],[{id:'out'}])}>
    <div className="flex items-start gap-2">
      <Icon name="FileText" size={16} className="text-slate-500 mt-0.5" />
      <div className="min-w-0">
        <div className="mono text-[10.5px] text-slate-700 truncate">/uploads/2026/invoices/</div>
        <div className="mono text-[11px] font-semibold text-slate-800 truncate">inv-00234.pdf</div>
        <div className="text-[10px] text-slate-500">248 KB · application/pdf</div>
      </div>
    </div>
  </CanvasNode>
); }

/* 6. AI */
function LLMNode(p) { return (
  <CanvasNode {...p} {...n('pink','Sparkles','LLM Completion','streaming · 512 tok',[{id:'in'}],[{id:'out'}], 280)}>
    <div className="flex items-center gap-2 mb-1.5">
      <Badge tone="pink" solid>GPT-4o</Badge>
      <span className="text-[10px] text-slate-500">temp 0.7</span>
    </div>
    <div className="rounded-lg bg-white border border-pink-100 px-2.5 py-1.5">
      <div className="text-[11px] text-slate-700 italic leading-snug">"Summarise this ticket as a single-line changelog entry, mentioning the…"</div>
    </div>
  </CanvasNode>
); }

function ChatMemoryNode(p) { return (
  <CanvasNode {...p} {...n('pink','BrainCircuit','Chat Memory','conversation buffer',[{id:'in'}],[{id:'out'}])}>
    <div className="flex items-end justify-between">
      <div>
        <div className="text-[10px] text-slate-500">buffer size</div>
        <div className="mono text-[18px] font-semibold text-slate-800 leading-none">12<span className="text-slate-400 text-[11px] ml-1">/ 20 turns</span></div>
      </div>
      <div className="flex items-end gap-0.5 h-8">
        {[4,7,5,9,6,8,11,7,10,12].map((h,i) => (
          <div key={i} className="w-1 rounded-sm bg-pink-400" style={{ height: `${h*2}px` }} />
        ))}
      </div>
    </div>
  </CanvasNode>
); }

function VectorStoreNode(p) { return (
  <CanvasNode {...p} {...n('pink','Database','Vector Search','top-k 5 · cosine',[{id:'in'}],[{id:'out'}])}>
    <div className="flex items-center gap-2 mb-1.5">
      <Badge tone="pink" solid>Pinecone</Badge>
      <span className="text-[10px] text-slate-500">idx · kb-docs</span>
    </div>
    <div className="mono text-[11px] text-slate-700 leading-snug truncate">q: "refund policy for subscriptions"</div>
  </CanvasNode>
); }

function AgentNode(p) { return (
  <CanvasNode {...p} {...n('pink','Bot','AI Agent','ReAct · max 8 steps',[{id:'in'}],[{id:'out'}], 280)}>
    <div className="text-[10px] text-slate-500 mb-1.5">tools available</div>
    <div className="flex flex-wrap gap-1">
      <Badge tone="emerald"><Icon name="Database" size={10} /> SQL</Badge>
      <Badge tone="blue"><Icon name="Globe" size={10} /> WEB</Badge>
      <Badge tone="amber"><Icon name="Mail" size={10} /> EMAIL</Badge>
      <Badge tone="cyan"><Icon name="Code2" size={10} /> CODE</Badge>
      <Badge tone="pink"><Icon name="Sparkles" size={10} /> RAG</Badge>
    </div>
  </CanvasNode>
); }

/* Registry for React Flow nodeTypes */
const NODE_TYPES = {
  cron: CronNode, webhook: WebhookNode, manual: ManualNode, subTrigger: SubWorkflowTriggerNode, queue: EventQueueTriggerNode,
  http: HttpRequestNode, sql: SqlDatabaseNode, email: EmailSenderNode, execSub: ExecuteSubWorkflowNode, nosql: NoSQLDatabaseNode,
  if: IfNode, switch: SwitchNode, loop: LoopNode, merge: MergeNode, errorCatch: ErrorCatchNode, wait: WaitNode,
  mapper: MapperNode, code: CodeNode, datetime: DateTimeNode, conv: DataConverterNode,
  state: GlobalStateNode, file: FileStorageNode,
  llm: LLMNode, mem: ChatMemoryNode, vector: VectorStoreNode, agent: AgentNode,
};

/* Meta used by the palette / add-menu */
const NODE_META = [
  { type:'cron',       group:'purple',  label:'Cron' },
  { type:'webhook',    group:'purple',  label:'Webhook' },
  { type:'manual',     group:'purple',  label:'Manual' },
  { type:'subTrigger', group:'purple',  label:'Sub-WF Start' },
  { type:'queue',      group:'purple',  label:'Queue' },
  { type:'http',       group:'emerald', label:'HTTP' },
  { type:'sql',        group:'emerald', label:'SQL' },
  { type:'email',      group:'emerald', label:'Email' },
  { type:'execSub',    group:'emerald', label:'Execute WF' },
  { type:'nosql',      group:'emerald', label:'NoSQL' },
  { type:'if',         group:'orange',  label:'If' },
  { type:'switch',     group:'orange',  label:'Switch' },
  { type:'loop',       group:'orange',  label:'Loop' },
  { type:'merge',      group:'orange',  label:'Merge' },
  { type:'errorCatch', group:'orange',  label:'Error Catch' },
  { type:'wait',       group:'orange',  label:'Wait' },
  { type:'mapper',     group:'cyan',    label:'Mapper' },
  { type:'code',       group:'cyan',    label:'Code' },
  { type:'datetime',   group:'cyan',    label:'Date/Time' },
  { type:'conv',       group:'cyan',    label:'Converter' },
  { type:'state',      group:'slate',   label:'State' },
  { type:'file',       group:'slate',   label:'File' },
  { type:'llm',        group:'pink',    label:'LLM' },
  { type:'mem',        group:'pink',    label:'Memory' },
  { type:'vector',     group:'pink',    label:'Vector' },
  { type:'agent',      group:'pink',    label:'Agent' },
];

Object.assign(window, { NODE_TYPES, NODE_META });
