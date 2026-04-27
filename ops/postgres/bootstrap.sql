-- Bootstrap MANUAL do banco Shift em nuvem.
--
-- Como o Postgres NAO sobe via Docker Compose (banco gerenciado em
-- Neon/Supabase/RDS/Cloud SQL/Azure DB), este script precisa ser aplicado
-- UMA UNICA VEZ no banco-alvo, pelo proprietario do projeto, ANTES da
-- primeira execucao do Alembic.
--
-- Exemplo de aplicacao:
--   psql "postgresql://user:pass@host:5432/db?sslmode=require" -f ops/postgres/bootstrap.sql
--
-- Ou, do dentro do container do backend (psql ja vem instalado):
--   docker compose run --rm shift-backend psql "$DATABASE_URL_PSQL" -f /app/../ops/postgres/bootstrap.sql
-- (DATABASE_URL_PSQL = mesmo URL, sem o prefixo +asyncpg)
--
-- Idempotente: pode ser aplicado mais de uma vez sem efeitos colaterais.

-- Necessario por compat com migrations Alembic que usam
--   sa.text('gen_random_uuid()')
-- Em Postgres 13+ a funcao ja existe no core, mas a extensao pgcrypto
-- precisa estar instalada para garantir o resolve em qualquer cluster.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Util para fuzzy search em lookups e nomes (descomente se necessario):
-- CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Verificacao rapida — apos rodar o script, este SELECT deve devolver 'ok':
-- SELECT 'ok' WHERE EXISTS (SELECT 1 FROM pg_extension WHERE extname='pgcrypto');
