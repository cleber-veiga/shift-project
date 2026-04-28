# Prompt Mestre — Identidade Visual SHIFT by VIASOFT

Prompt para enviar a uma IA generativa de imagem com o objetivo de produzir um **Brand Concept Board** completo da plataforma SHIFT.

---

**Crie um sistema de Identidade Visual completo, moderno, técnico e confiável para o produto SHIFT, uma plataforma de integração, migração e automação de dados desenvolvida pela VIASOFT, que conecta ERPs legados (Firebird, Oracle) a data warehouses modernos (PostgreSQL, DW) com orquestração inteligente e assistência de IA.**

O resultado deve ser apresentado em formato de **"Mural de Conceito de Marca" (Brand Concept Board)**, mostrando todos os elementos aplicados e harmonizados em uma única imagem de alta resolução, no estilo de uma landing page de apresentação de marca premium.

## Diretrizes Estratégicas (O "Feeling" da Marca)

- **O Produto (SHIFT):** Plataforma técnica para engenheiros de dados e times de TI. Move dados do legado para o moderno — o nome "SHIFT" representa literalmente essa transição. Deve transmitir **fluxo de dados, orquestração, confiabilidade técnica, observabilidade e inteligência (IA generativa no Playground SQL).** O público é técnico: desenvolvedores, DBAs, analistas de dados, arquitetos de integração.
- **A Empresa (VIASOFT):** Gigante de TI brasileira consolidada, com forte presença em ERPs do varejo, distribuição e indústria. O SHIFT é o produto *infra/plataforma* dentro do ecossistema — herda credibilidade corporativa da VIASOFT mas se posiciona como ferramenta moderna de engenharia, no patamar de Airbyte, Fivetran ou Dagster.
- **Tom:** Sério, técnico, mas não burocrático. Inspirado em produtos como Linear, Vercel, Supabase e Dagster — clean, com leve toque de "synthwave técnico" nos detalhes (gradientes vibrantes em fundos escuros).

## Requisitos Visuais Específicos

### 1. Logotipo e Variações (Logotype System)
- **Conceito:** O nome "**SHIFT**" em tipografia sans-serif geométrica, robusta, em caixa alta. O conceito visual deve sugerir **deslocamento horizontal** — a letra "I" pode ter um traço/seta cinético apontando para frente, ou o "F" e "T" podem estar levemente desalinhados na vertical (efeito "shift" tipográfico, como teclas Shift de teclado deslocando caracteres). Outra opção: o "H" ou "I" com linhas paralelas que evocam **fluxo de dados em pipeline**.
- **Sub-marca:** Abaixo de "SHIFT", em fonte humanist menor, a assinatura "**by VIASOFT**" ou "**Uma plataforma VIASOFT**".
- **Isotipo:** Símbolo isolado derivado do elemento de movimento — ideal para favicons, app icons e badges. Deve funcionar em 16x16px (já que a frontend Next.js usa um `icon.svg`).
- **Variações obrigatórias:** Horizontal (principal), empilhado (quadrado, para avatares e cards), monocromático preto, monocromático branco (para fundos escuros do dashboard) e isotipo isolado.

### 2. Paleta de Cores (Color Palette & Harmony)
- **Conceito:** Paleta dual — uma "luz" (corporativa, para materiais institucionais e modo claro do app) e uma "escura" (técnica, para o dashboard real onde engenheiros passam o dia, modo escuro como padrão).
- **Primária — Gradiente "Data Flow":** De **Azul Elétrico Profundo** (#1E40FF aprox.) para **Ciano/Turquesa** (#00D4FF) ou para **Violeta/Roxo Tech** (#7C3AED). Esse gradiente representa o "shift" do legado (azul profundo, estabilidade) para o moderno (ciano vibrante, energia).
- **Secundária (Estabilizadora — VIASOFT):** Navy Blue Corporativo (#0A1F44) e Cinza Grafite (#1F2937).
- **Acento Funcional (estados do produto):**
  - Verde sucesso (#10B981) — execuções OK, conexão validada
  - Âmbar atenção (#F59E0B) — pipelines em retry, warnings
  - Vermelho falha (#EF4444) — runs com erro
- **Apoio:** Branco Puro (#FFFFFF), Cinza Ultra-claro (#F8FAFC) e Preto Profundo (#0B0F19) para o tema escuro do dashboard.

### 3. Tipografia (Typography System)
- **Títulos / Logo:** Geometric Sans-Serif moderna — *Space Grotesk*, *Mont* ou *Poppins* — pesos *Bold* e *Black*.
- **Interface e Corpo:** Humanist Sans-Serif — *Inter* (já é padrão do shadcn/ui usado no frontend) — pesos *Regular*, *Medium* e *Semibold*.
- **Código / Queries SQL / Logs de execução:** Monoespaçada técnica — *JetBrains Mono* ou *Fira Code* — essencial pois o produto tem editor SQL e visualização de logs de execução.

### 4. Elementos Gráficos e Padrão (Graphic Patterns)
- **Estilo "Pipeline & Fluxo":** Padrões inspirados em **DAGs (Directed Acyclic Graphs)** — nós conectados por linhas finas, representando workflows de ETL. Linhas que partem de blocos quadrados (fontes legadas) e convergem em blocos arredondados (DW moderno).
- **Padrão Secundário — "Schema":** Grade sutil tipo blueprint técnico, evocando estrutura de tabelas e schemas de banco.
- **Animação implícita:** Nos mockups, sugira **partículas de dados fluindo** ao longo das linhas dos pipelines (efeito de pontos brilhantes em movimento), como nas visualizações do Airflow e Dagster.

### 5. Iconografia (Iconography System)
- **Estilo:** Line-art minimalista, traço 1.5px, cantos levemente arredondados, alinhado com a estética do shadcn/ui + Lucide (já usados no frontend).
- **Conjunto temático obrigatório:** ícones para Conexão, Workflow, Execução, Playground SQL, Schema, Firebird (cilindro com chama estilizada), PostgreSQL, IA (chip com sparkle), Workspace, Projeto.
- **Uso de cor:** Cinza grafite no estado padrão, gradiente primário no estado ativo/hover.

### 6. Direção Fotográfica e Ilustrativa (Visual Direction)
- **Mood:** Engenharia de dados moderna, dark mode, foco e fluxo.
- **Cenas reais (fotografia):** Engenheiros de dados em monitores ultrawide com dashboards de pipelines, code editors abertos com SQL, ambientes de escritório técnico bem iluminados, hands-on em teclados mecânicos, telas com gráficos de execução em tempo real.
- **Ilustrações abstratas:** Renders 3D de **fluxos de dados luminosos** entre cubos representando bancos de dados, estética inspirada em Stripe, Vercel e Dagster. Profundidade de campo rasa, bokeh azul/violeta.

## Requisitos de Aplicação (Mockups)

A imagem final deve conter simulações de aplicação real **alinhadas ao produto**:

- **Mockup do Dashboard Web (hero):** Tela do editor visual de workflows do SHIFT em monitor ultrawide — nodes conectados (Extract Firebird → Transform → Load PostgreSQL), tema escuro, painel lateral com lista de execuções recentes e gradiente sutil ao fundo.
- **Mockup do Playground SQL com IA:** Tela mostrando o assistente SQL em ação — editor de query à esquerda, chat de IA com streaming SSE e raciocínio ReAct visível à direita (tool calls como `inspect_schema`, `count_rows`).
- **Mockup Mobile / Tablet:** Tela de **monitoramento de execuções** em tablet — cards de runs com status (sucesso/falha/retry) e badge "by VIASOFT".
- **Mockup de Login:** Tela de login limpa com logo SHIFT, opção "Entrar com Google" e gradiente primário no botão CTA.
- **Mockup de Documentação Técnica:** Página de docs no estilo MkDocs Material (já é o stack do `mkdocs.yml` do projeto) com sidebar, code blocks em JetBrains Mono e o logo SHIFT no header.
- **Mockup de Cartão de Visita:** Cartão premium preto fosco, logo em hot stamping com gradiente metálico, verso com padrão DAG sutil.
- **Mockup de Recepção VIASOFT:** Parede de lobby moderno com logo "**SHIFT** by VIASOFT" em acrílico 3D retroiluminado pelo gradiente azul→violeta.
- **Mockup de Terminal CLI:** Print de terminal mostrando saída do `docker compose up` da stack SHIFT, com o logo ASCII e cores do tema (referência ao stack Docker do projeto).
- **Capa do Brandbook:** Capa do manual com o título "**SHIFT – Diretrizes de Identidade Visual da Plataforma de Dados**" sobre fundo escuro com padrão de pipeline luminoso.

## Estilo Final da Imagem

Layout de **mural editorial premium**, fundo predominantemente escuro (#0B0F19) com seções claras de respiro, tipografia hierárquica clara, cada bloco rotulado com legendas técnicas em Inter, formato 16:9 ou 4:5 em ultra-alta resolução. Inspiração direta: brand boards da Linear, Vercel, Supabase e Dagster.
