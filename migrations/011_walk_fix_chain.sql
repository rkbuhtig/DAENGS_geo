-- pause/resume 경계를 원좌표와 함께 보존한다. 같은 세션의 두 chain 사이에는
-- 시간·거리가 가까워도 segment가 없다. 기존 클라이언트는 단일 chain(0)으로 읽는다.
ALTER TABLE walk_fix
    ADD COLUMN IF NOT EXISTS chain_index INTEGER NOT NULL DEFAULT 0;

DO $$ BEGIN
    ALTER TABLE walk_fix
        ADD CONSTRAINT walk_fix_chain_index_nonnegative CHECK (chain_index >= 0);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
